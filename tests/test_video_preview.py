from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from comfort_z import api
from comfort_z.models import MonitoringProfile, MonitoringSourceType
from comfort_z.services.media import LocalMediaStore
from comfort_z.services import video_preview


VIDEO_BYTES = b"\x00\x00\x00\x18ftypisom0123456789abcdefghijklmnopqrstuvwxyz"


def profile(
    source_reference="gs://private-animal-media/raku.mp4",
    source_type=MonitoringSourceType.VIDEO,
):
    return MonitoringProfile(
        animal_id="raku",
        animal_name="Raku",
        monitoring_goal="Keep an eye on Raku.",
        source_reference=source_reference,
        source_type=source_type,
        normal_sampling_interval_seconds=300,
        elevated_sampling_interval_seconds=60,
        daily_sample_budget=24,
        samples_used_in_current_period=3,
        source_cursor_seconds=12.5,
        source_cursor_frame_index=375,
    )


class FakeRepository:
    def __init__(self, saved_profile):
        self.saved_profile = saved_profile

    def get_profile(self, animal_id):
        return self.saved_profile if animal_id == "raku" else None


class FakeBlob:
    def __init__(self, content=VIDEO_BYTES):
        self.content = content
        self.size = len(content)
        self.content_type = "video/mp4"
        self.reload_calls = 0
        self.open_calls = 0

    def reload(self):
        self.reload_calls += 1

    def open(self, mode, chunk_size):
        assert mode == "rb"
        assert chunk_size == video_preview.STREAM_CHUNK_BYTES
        self.open_calls += 1
        return BytesIO(self.content)


class FakeBucket:
    def __init__(self, blob):
        self.blob_instance = blob
        self.object_names = []

    def blob(self, object_name):
        self.object_names.append(object_name)
        return self.blob_instance


class FakeStorageClient:
    def __init__(self, bucket):
        self.bucket_instance = bucket
        self.bucket_names = []

    def bucket(self, bucket_name):
        self.bucket_names.append(bucket_name)
        return self.bucket_instance


def configure_api(monkeypatch, saved_profile):
    monkeypatch.setattr(
        api, "get_monitoring_state_repository", lambda: FakeRepository(saved_profile)
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("source preview must not run or mutate monitoring")

    monkeypatch.setattr(api, "monitor_animal", forbidden)
    monkeypatch.setattr(api, "monitor_next_window", forbidden)
    return TestClient(api.app)


def test_private_gcs_preview_supports_full_and_range_responses_without_state_change(
    monkeypatch,
):
    saved_profile = profile()
    before = saved_profile.model_dump(mode="json")
    client = configure_api(monkeypatch, saved_profile)
    blob = FakeBlob()
    bucket = FakeBucket(blob)
    storage_client = FakeStorageClient(bucket)
    monkeypatch.setattr(
        video_preview, "_default_storage_client", lambda: storage_client
    )

    full = client.get(
        "/animals/raku/monitoring-source-preview",
        params={"source_reference": "gs://other-bucket/secret.mp4"},
    )
    partial = client.get(
        "/animals/raku/monitoring-source-preview",
        headers={"Range": "bytes=8-15"},
    )

    assert full.status_code == 200
    assert full.content == VIDEO_BYTES
    assert full.headers["content-type"].startswith("video/mp4")
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(VIDEO_BYTES))
    assert partial.status_code == 206
    assert partial.content == VIDEO_BYTES[8:16]
    assert partial.headers["content-range"] == f"bytes 8-15/{len(VIDEO_BYTES)}"
    assert partial.headers["content-length"] == "8"
    assert storage_client.bucket_names == ["private-animal-media", "private-animal-media"]
    assert bucket.object_names == ["raku.mp4", "raku.mp4"]
    assert saved_profile.model_dump(mode="json") == before


def test_invalid_video_range_returns_416(monkeypatch):
    client = configure_api(monkeypatch, profile())
    blob = FakeBlob()
    monkeypatch.setattr(
        video_preview,
        "_default_storage_client",
        lambda: FakeStorageClient(FakeBucket(blob)),
    )

    response = client.get(
        "/animals/raku/monitoring-source-preview",
        headers={"Range": f"bytes={len(VIDEO_BYTES)}-"},
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(VIDEO_BYTES)}"
    assert response.headers["accept-ranges"] == "bytes"
    assert blob.open_calls == 0


@pytest.mark.parametrize(
    ("saved_profile", "animal_id", "expected_status", "expected_detail"),
    [
        (None, "missing", 404, "Animal profile was not found."),
        (profile(None, None), "raku", 409, "Monitoring source is not connected."),
        (
            profile(0, MonitoringSourceType.WEBCAM),
            "raku",
            409,
            "Configured monitoring source is not a video.",
        ),
    ],
)
def test_missing_source_and_non_video_profiles_are_rejected_safely(
    monkeypatch, saved_profile, animal_id, expected_status, expected_detail
):
    client = configure_api(monkeypatch, saved_profile)

    response = client.get(f"/animals/{animal_id}/monitoring-source-preview")

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_local_preview_accepts_only_generated_media_references(tmp_path, monkeypatch):
    store = LocalMediaStore(tmp_path / "media")
    stored = store.save_video(
        VIDEO_BYTES, content_type="video/mp4", original_name="raku.mp4"
    )
    monkeypatch.setattr(video_preview, "get_local_media_store", lambda: store)
    client = configure_api(monkeypatch, profile(stored.reference))

    response = client.get(
        "/animals/raku/monitoring-source-preview", headers={"Range": "bytes=-5"}
    )

    assert response.status_code == 206
    assert response.content == VIDEO_BYTES[-5:]

    unsafe_client = configure_api(monkeypatch, profile(str(tmp_path / "secret.mp4")))
    unsafe_response = unsafe_client.get("/animals/raku/monitoring-source-preview")
    assert unsafe_response.status_code == 404
    assert unsafe_response.json()["detail"] == "Configured video preview is unavailable."
