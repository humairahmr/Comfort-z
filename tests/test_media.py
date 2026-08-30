from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from comfort_z import api
from comfort_z.models import MonitoringProfile, MonitoringSourceType
from comfort_z.services import media as media_module
from comfort_z.services.media import LocalMediaStore, MediaStorageError
from comfort_z.services.orchestration import (
    connect_monitoring_source,
    create_or_update_monitoring_profile,
    set_profile_location,
    set_profile_photo_reference,
)
from comfort_z.services.repository import LocalJsonMonitoringStateRepository
from comfort_z.services.source import resolve_video_source


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00portrait"
PNG = b"\x89PNG\r\n\x1a\nportrait"
WEBP = b"RIFF\x10\x00\x00\x00WEBPportrait"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2"


def profile(**updates):
    values = {
        "animal_id": "milo",
        "animal_name": "Milo",
        "monitoring_goal": "Keep an eye on Milo.",
        "source_reference": 0,
        "source_type": MonitoringSourceType.WEBCAM,
        "normal_sampling_interval_seconds": 300,
        "elevated_sampling_interval_seconds": 60,
        "daily_sample_budget": 24,
        "samples_used_in_current_period": 3,
        "budget_period_date": date(2026, 8, 30),
        "source_cursor_seconds": 12.5,
        "source_cursor_frame_index": 42,
        "active": True,
    }
    values.update(updates)
    return MonitoringProfile(**values)


def test_profile_photo_upload_is_validated_and_stored_with_generated_reference(tmp_path):
    store = LocalMediaStore(tmp_path / "media")

    stored = store.save_profile_photo(
        JPEG, content_type="image/jpeg", original_name="../../Milo portrait.jpg"
    )

    assert stored.reference.startswith("profile-photo/")
    assert stored.reference.endswith(".jpg")
    assert ".." not in stored.reference
    assert store.resolve(stored.reference).parent == (tmp_path / "media" / "profile-photo").resolve()
    assert store.public_url(stored.reference).startswith("/media/profile-photo/")


@pytest.mark.parametrize(
    ("content", "content_type", "filename", "stored_suffix"),
    [
        (JPEG, "image/jpeg", "portrait.jpg", ".jpg"),
        (JPEG, "image/jpeg", "portrait.jpeg", ".jpg"),
        (JPEG, "image/jpeg", "portrait.jfif", ".jpg"),
        (PNG, "image/png", "portrait.png", ".png"),
        (WEBP, "image/webp", "portrait.webp", ".webp"),
    ],
)
def test_profile_photo_accepts_supported_image_extensions(
    tmp_path, content, content_type, filename, stored_suffix
):
    stored = LocalMediaStore(tmp_path / "media").save_profile_photo(
        content, content_type=content_type, original_name=filename
    )

    assert stored.reference.endswith(stored_suffix)


@pytest.mark.parametrize(
    ("content", "content_type", "filename"),
    [
        (b"not-an-image", "image/jpeg", "portrait.jpg"),
        (JPEG, "application/octet-stream", "portrait.jpg"),
        (JPEG, "image/jpeg", "portrait.png"),
    ],
)
def test_profile_photo_rejects_invalid_or_mismatched_content(tmp_path, content, content_type, filename):
    store = LocalMediaStore(tmp_path / "media")

    with pytest.raises(MediaStorageError):
        store.save_profile_photo(content, content_type=content_type, original_name=filename)


def test_profile_photo_rejects_oversized_content(tmp_path, monkeypatch):
    monkeypatch.setattr(media_module, "MAX_PROFILE_PHOTO_BYTES", 4)
    store = LocalMediaStore(tmp_path / "media")

    with pytest.raises(MediaStorageError, match="exceeds"):
        store.save_profile_photo(JPEG, content_type="image/jpeg", original_name="portrait.jpg")


def test_video_upload_is_validated_stored_and_cannot_escape_media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(media_module, "MAX_VIDEO_UPLOAD_BYTES", len(MP4))
    store = LocalMediaStore(tmp_path / "media")

    stored = store.save_video(MP4, content_type="video/mp4", original_name="..\\..\\Milo clip.mp4")

    assert stored.reference.startswith("video/")
    assert store.resolve(stored.reference).parent == (tmp_path / "media" / "video").resolve()
    with pytest.raises(MediaStorageError):
        store.resolve("video/../../outside.mp4")
    with pytest.raises(MediaStorageError, match="exceeds"):
        store.save_video(MP4 + b"x", content_type="video/mp4", original_name="large.mp4")
    with pytest.raises(MediaStorageError):
        store.save_video(b"not-video", content_type="video/mp4", original_name="unsafe.mp4")


def test_profile_photo_changes_no_monitoring_state(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    original = profile()
    repository.save_profile(original)

    saved = set_profile_photo_reference(
        "milo", "profile-photo/0123456789abcdef0123456789abcdef.jpg", state_repository=repository
    )

    assert saved.profile_photo_reference.endswith(".jpg")
    assert saved.source_reference == original.source_reference
    assert saved.source_type == original.source_type
    assert saved.active == original.active
    assert saved.source_cursor_seconds == original.source_cursor_seconds
    assert saved.source_cursor_frame_index == original.source_cursor_frame_index
    assert saved.samples_used_in_current_period == original.samples_used_in_current_period
    reloaded = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json").get_profile("milo")
    assert reloaded is not None
    assert reloaded.profile_photo_reference == saved.profile_photo_reference


def test_profile_location_changes_only_location_fields(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    original = profile(location_name=None, latitude=None, longitude=None)
    repository.save_profile(original)

    saved = set_profile_location(
        "milo",
        location_name="Kuching, Sarawak",
        latitude=1.5533,
        longitude=110.3592,
        state_repository=repository,
    )

    assert saved.location_name == "Kuching, Sarawak"
    assert saved.latitude == 1.5533
    assert saved.longitude == 110.3592
    assert saved.source_reference == original.source_reference
    assert saved.source_type == original.source_type
    assert saved.active == original.active
    assert saved.source_cursor_seconds == original.source_cursor_seconds
    assert saved.source_cursor_frame_index == original.source_cursor_frame_index
    assert saved.samples_used_in_current_period == original.samples_used_in_current_period
    reloaded = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json").get_profile("milo")
    assert reloaded is not None
    assert reloaded.location_name == "Kuching, Sarawak"


def test_uploaded_video_resolves_only_from_the_app_media_store(tmp_path, monkeypatch):
    store = LocalMediaStore(tmp_path / "media")
    stored = store.save_video(MP4, content_type="video/mp4", original_name="milo.mp4")
    monkeypatch.setattr("comfort_z.services.source.get_local_media_store", lambda: store)

    with resolve_video_source(stored.reference) as resolved:
        assert resolved.local_source == str(store.resolve(stored.reference))
        assert resolved.source_label == "uploaded video"


def test_api_uploads_photo_and_video_without_running_monitoring(tmp_path, monkeypatch):
    state_path = tmp_path / "monitoring_state.json"
    monkeypatch.setenv("OBSERVATION_STORE", "local")
    monkeypatch.setenv("LOCAL_MONITORING_STATE_FILE", str(state_path))
    store = LocalMediaStore(tmp_path / "media")
    monkeypatch.setattr(api, "get_local_media_store", lambda: store)
    repository = LocalJsonMonitoringStateRepository(state_path)
    create_or_update_monitoring_profile(profile(), state_repository=repository)
    monkeypatch.setattr(
        api,
        "monitor_next_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("upload must not monitor")),
    )
    monkeypatch.setattr(
        api,
        "monitor_animal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("upload must not call Gemini")),
    )

    client = TestClient(api.app)
    photo_response = client.post(
        "/animals/milo/profile-photo",
        files={"photo": ("../../portrait.jpg", JPEG, "image/jpeg")},
    )
    video_response = client.post(
        "/monitoring/milo/video-source",
        files={"video": ("Milo clip.mp4", MP4, "video/mp4")},
    )

    assert photo_response.status_code == 200
    photo_url = photo_response.json()["profile_photo_url"]
    assert photo_url.startswith("/media/profile-photo/")
    served_photo = client.get(photo_url)
    assert served_photo.status_code == 200
    assert served_photo.headers["content-type"].startswith("image/jpeg")
    assert served_photo.content == JPEG
    persisted_photo = LocalJsonMonitoringStateRepository(state_path).get_profile("milo")
    assert persisted_photo is not None
    assert persisted_photo.profile_photo_reference == photo_response.json()["profile_photo_reference"]
    assert client.get("/monitoring/milo/profile").json()["profile_photo_url"] == photo_url
    assert client.get("/animals").json()[0]["profile_photo_url"] == photo_url
    assert video_response.status_code == 200
    assert video_response.json()["source_type"] == "video"
    assert video_response.json()["source_display_name"] == "Milo clip.mp4"
    saved = repository.get_profile("milo")
    assert saved is not None
    assert saved.source_reference.startswith("video/")
    assert saved.source_type == MonitoringSourceType.VIDEO
    assert saved.active is False
    assert saved.source_cursor_seconds == 0
    assert saved.source_cursor_frame_index is None
    assert saved.samples_used_in_current_period == 3


def test_api_updates_location_without_replacing_profile_state(tmp_path, monkeypatch):
    state_path = tmp_path / "monitoring_state.json"
    monkeypatch.setenv("OBSERVATION_STORE", "local")
    monkeypatch.setenv("LOCAL_MONITORING_STATE_FILE", str(state_path))
    repository = LocalJsonMonitoringStateRepository(state_path)
    original = profile()
    repository.save_profile(original)
    client = TestClient(api.app)

    response = client.put(
        "/monitoring/milo/location",
        json={
            "location_name": "Kuching, Sarawak",
            "latitude": 1.5533,
            "longitude": 110.3592,
        },
    )

    assert response.status_code == 200
    assert response.json()["location_name"] == "Kuching, Sarawak"
    saved = LocalJsonMonitoringStateRepository(state_path).get_profile("milo")
    assert saved is not None
    assert saved.latitude == 1.5533
    assert saved.longitude == 110.3592
    assert saved.source_reference == original.source_reference
    assert saved.active == original.active
    assert saved.source_cursor_seconds == original.source_cursor_seconds
    assert saved.samples_used_in_current_period == original.samples_used_in_current_period
    assert client.put(
        "/monitoring/milo/location", json={"location_name": "Kuching", "latitude": 1.5533}
    ).status_code == 422


def test_profile_payload_uses_fallback_when_a_photo_object_is_missing(tmp_path, monkeypatch):
    store = LocalMediaStore(tmp_path / "media")
    monkeypatch.setattr(api, "get_local_media_store", lambda: store)
    missing = profile(profile_photo_reference="profile-photo/0123456789abcdef0123456789abcdef.jpg")

    assert api._profile_payload(missing)["profile_photo_url"] is None


def test_video_source_change_resets_only_source_cursor_and_pauses(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    original = profile()
    repository.save_profile(original)

    saved = connect_monitoring_source(
        "milo",
        source_reference="video/0123456789abcdef0123456789abcdef.mp4",
        source_type=MonitoringSourceType.VIDEO,
        source_display_name="Milo clip.mp4",
        state_repository=repository,
    )

    assert saved.source_type == MonitoringSourceType.VIDEO
    assert saved.source_display_name == "Milo clip.mp4"
    assert saved.active is False
    assert saved.source_cursor_seconds == 0
    assert saved.source_cursor_frame_index is None
    assert saved.samples_used_in_current_period == original.samples_used_in_current_period
