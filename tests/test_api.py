from fastapi.testclient import TestClient
import pytest

from comfort_z import api
from comfort_z.models import VoiceOwnerUpdateDraftResponse
from comfort_z.services.video import VideoMonitoringService


def test_health_reports_agent_model_and_configured_store(monkeypatch):
    monkeypatch.setenv("OBSERVATION_STORE", "firestore")
    response = TestClient(api.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "agent": "comfort_z",
        "model": "gemini-3.5-flash",
        "observation_store": "firestore",
    }


def test_monitor_endpoint_delegates_to_existing_monitoring_tool(monkeypatch):
    received = {}

    def fake_monitor_animal(**kwargs):
        received.update(kwargs)
        return {"decision": {"alert_status": False}}

    monkeypatch.setattr(api, "monitor_animal", fake_monitor_animal)
    response = TestClient(api.app).post(
        "/monitor",
        json={
            "animal_id": "raku",
            "image_path": "/tmp/raku-frame.jpg",
            "animal_name": "Raku",
            "expected_species": "Betta splendens",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"decision": {"alert_status": False}}
    assert received["animal_id"] == "raku"
    assert received["expected_species"] == "Betta splendens"


def test_history_endpoint_delegates_to_existing_history_tool(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_recent_observations",
        lambda animal_id, limit: [{"animal_id": animal_id, "limit": limit}],
    )

    response = TestClient(api.app).get("/animals/raku/observations?limit=3")

    assert response.status_code == 200
    assert response.json() == [{"animal_id": "raku", "limit": 3}]


def test_owner_update_endpoints_are_separate_from_monitoring_tools(monkeypatch):
    received = {}

    def save_owner_update(animal_id, category, occurred_at, note, reading, input_method):
        received.update(
            animal_id=animal_id,
            category=category,
            occurred_at=occurred_at,
            note=note,
            reading=reading,
            input_method=input_method,
        )
        return {"owner_update_id": "update-1", "animal_id": animal_id, "category": category}

    monkeypatch.setattr(api, "record_owner_update", save_owner_update)
    monkeypatch.setattr(
        api,
        "get_recent_owner_updates",
        lambda animal_id, limit: [{"animal_id": animal_id, "limit": limit, "source": "owner"}],
    )
    monkeypatch.setattr(
        api,
        "monitor_next_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("monitoring must not run")),
    )
    monkeypatch.setattr(
        api,
        "generate_daily_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reporting must not run")),
    )
    client = TestClient(api.app)

    created = client.post(
        "/animals/milo/owner-updates",
        json={"category": "feeding", "note": "Fed Milo at 8 PM."},
    )
    listed = client.get("/animals/milo/owner-updates?limit=7")

    assert created.status_code == 200
    assert created.json()["owner_update_id"] == "update-1"
    assert received["animal_id"] == "milo"
    assert received["category"] == "feeding"
    assert received["input_method"] == "typed"
    assert listed.status_code == 200
    assert listed.json() == [{"animal_id": "milo", "limit": 7, "source": "owner"}]


def test_confirmed_owner_update_accepts_voice_input_method(monkeypatch):
    received = {}

    def save_owner_update(animal_id, category, occurred_at, note, reading, input_method):
        received["input_method"] = input_method
        return {"owner_update_id": "voice-1", "animal_id": animal_id}

    monkeypatch.setattr(api, "record_owner_update", save_owner_update)
    response = TestClient(api.app).post(
        "/animals/raku/owner-updates",
        json={"category": "feeding", "note": "Fed Raku.", "input_method": "voice"},
    )

    assert response.status_code == 200
    assert response.json()["owner_update_id"] == "voice-1"
    assert received["input_method"] == "voice"


def test_voice_draft_endpoint_is_transient_and_delegates_only_to_voice_service(monkeypatch):
    received = {}

    def create_drafts(animal_id, **kwargs):
        received["animal_id"] = animal_id
        received.update(kwargs)
        return VoiceOwnerUpdateDraftResponse.model_validate({
            "transcript": "Fed Raku.",
            "drafts": [{"category": "feeding", "occurred_at": "2026-08-30T12:00:00Z", "note": "Fed Raku."}],
            "review_warnings": [],
        })

    monkeypatch.setattr(api, "create_voice_owner_update_drafts", create_drafts)
    monkeypatch.setattr(api, "record_owner_update", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not persist")))
    monkeypatch.setattr(api, "monitor_next_window", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not monitor")))
    monkeypatch.setattr(api, "generate_daily_report", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not report")))

    response = TestClient(api.app).post(
        "/animals/raku/owner-update-drafts/voice",
        files={"audio": ("update.webm", b"audio", "audio/webm")},
        data={
            "capture_timestamp": "2026-08-30T12:00:00Z",
            "capture_duration_ms": "1200",
            "browser_timezone": "Asia/Kuala_Lumpur",
            "locale": "en-MY",
        },
    )

    assert response.status_code == 200
    assert response.json()["transcript"] == "Fed Raku."
    assert received["animal_id"] == "raku"
    assert received["mime_type"] == "audio/webm"
    assert received["audio_bytes"] == b"audio"


def test_voice_draft_endpoint_returns_a_safe_fallback_for_unavailable_voice_service(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise api.VoiceUpdateUnavailableError("internal details must not reach the browser")

    monkeypatch.setattr(api, "create_voice_owner_update_drafts", unavailable)

    response = TestClient(api.app).post(
        "/animals/raku/owner-update-drafts/voice",
        files={"audio": ("update.webm", b"audio", "audio/webm")},
        data={
            "capture_timestamp": "2026-08-30T12:00:00Z",
            "capture_duration_ms": "1200",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Voice updates are temporarily unavailable. You can add an update manually."
    }


def test_owner_update_endpoint_rejects_malformed_combinations():
    client = TestClient(api.app)

    missing_reading = client.post("/animals/milo/owner-updates", json={"category": "measurement"})
    note_with_reading = client.post(
        "/animals/milo/owner-updates",
        json={
            "category": "feeding",
            "note": "Fed Milo.",
            "reading": {"reading_type": "water temperature", "value": 27, "unit": "C"},
        },
    )

    assert missing_reading.status_code == 422
    assert note_with_reading.status_code == 422


def test_owner_update_unknown_animal_maps_to_not_found(monkeypatch):
    def missing(*_args, **_kwargs):
        raise api.MonitoringProfileNotFoundError("internal")

    monkeypatch.setattr(api, "record_owner_update", missing)
    response = TestClient(api.app).post(
        "/animals/missing/owner-updates", json={"category": "note", "note": "Owner context."}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Animal profile was not found."}


def test_monitor_endpoint_returns_non_sensitive_storage_error(monkeypatch):
    def unavailable(**_kwargs):
        raise api.ObservationRepositoryError("network details should not reach the client")

    monkeypatch.setattr(api, "monitor_animal", unavailable)
    response = TestClient(api.app).post(
        "/monitor",
        json={"animal_id": "raku", "image_path": "/tmp/raku-frame.jpg"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Observation storage is unavailable."


def test_monitoring_profile_and_bounded_window_endpoints_delegate_to_tools(monkeypatch):
    received = {}

    def save_profile(**kwargs):
        received.update(kwargs)
        return {"animal_id": kwargs["animal_id"], "active": True}

    monkeypatch.setattr(
        api,
        "create_monitoring_profile",
        save_profile,
    )
    monkeypatch.setattr(
        api,
        "monitor_next_window",
        lambda animal_id, window_max_samples: {
            "animal_id": animal_id,
            "ended_reason": "max_samples_reached",
            "window_max_samples": window_max_samples,
        },
    )
    client = TestClient(api.app)

    profile = client.post(
        "/monitoring/profiles",
        json={
            "animal_id": "raku",
            "monitoring_goal": "Keep an eye on Raku.",
            "source_reference": "Raku.mp4",
            "source_type": "video",
            "location_name": "Test location",
            "latitude": 1.0,
            "longitude": 2.0,
            "enclosure_type": "aquarium",
            "direct_environment_readings": [
                {"reading_type": "water_temperature", "value": 26, "unit": "C"}
            ],
        },
    )
    window = client.post("/monitoring/raku/next-window", json={"window_max_samples": 2})

    assert profile.status_code == 200
    assert profile.json() == {"animal_id": "raku", "active": True}
    assert received["latitude"] == 1.0
    assert received["direct_environment_readings"][0]["source"] == "owner"
    assert window.status_code == 200
    assert window.json()["window_max_samples"] == 2


def test_source_less_profile_request_is_accepted_and_source_fields_are_omitted(monkeypatch):
    received = {}

    def save_profile(**kwargs):
        received.update(kwargs)
        return {"animal_id": kwargs["animal_id"], "active": True, "source_reference": None, "source_type": None}

    monkeypatch.setattr(api, "create_monitoring_profile", save_profile)
    response = TestClient(api.app).post(
        "/monitoring/profiles",
        json={"animal_id": "milo-a1b2c3", "animal_name": "Milo", "monitoring_goal": "Keep an eye on Milo."},
    )

    assert response.status_code == 200
    assert response.json()["source_reference"] is None
    assert response.json()["source_type"] is None
    assert received["source_reference"] is None
    assert received["source_type"] is None


def test_list_animals_includes_a_source_less_profile(monkeypatch):
    class FakeProfile:
        def model_dump(self, mode=None):
            return {
                "animal_id": "milo-a1b2c3",
                "animal_name": "Milo",
                "monitoring_goal": "Keep an eye on Milo.",
                "source_reference": None,
                "source_type": None,
                "active": True,
            }

    class FakeRepo:
        def list_profiles(self):
            return [FakeProfile()]

    monkeypatch.setattr(api, "get_monitoring_state_repository", lambda: FakeRepo())
    response = TestClient(api.app).get("/animals")

    assert response.status_code == 200
    assert response.json()[0]["source_reference"] is None
    assert response.json()[0]["source_type"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"source_reference": "milo.mp4"},
        {"source_type": "video"},
    ],
)
def test_profile_request_rejects_an_unpaired_source_field(payload):
    body = {"animal_id": "milo", "monitoring_goal": "Keep an eye on Milo."}
    body.update(payload)

    response = TestClient(api.app).post("/monitoring/profiles", json=body)

    assert response.status_code == 422


def test_source_less_daily_report_error_is_mapped_cleanly(monkeypatch):
    def source_not_connected(_animal_id):
        raise api.MonitoringSourceNotConnectedError("internal detail")

    monkeypatch.setattr(api, "generate_daily_report", source_not_connected)
    response = TestClient(api.app).post("/monitoring/milo/daily-report")

    assert response.status_code == 409
    assert response.json() == {"detail": "Monitoring source is not connected."}


def test_daily_report_endpoints_delegate_to_existing_orchestration_tools(monkeypatch):
    monkeypatch.setattr(
        api,
        "generate_daily_report",
        lambda animal_id: {"animal_id": animal_id, "report_id": "report-1"},
    )
    monkeypatch.setattr(
        api,
        "get_recent_daily_reports",
        lambda animal_id, limit: [{"animal_id": animal_id, "limit": limit}],
    )
    client = TestClient(api.app)

    generated = client.post("/monitoring/raku/daily-report")
    history = client.get("/animals/raku/reports?limit=3")

    assert generated.status_code == 200
    assert generated.json()["report_id"] == "report-1"
    assert history.status_code == 200
    assert history.json() == [{"animal_id": "raku", "limit": 3}]


def test_list_animals_endpoint_delegates_to_state_repository(monkeypatch):
    class FakeProfile:
        def model_dump(self, mode=None):
            return {
                "animal_id": "raku",
                "animal_name": "Raku",
                "expected_species": "Betta splendens",
                "active": True,
            }

    class FakeRepo:
        def list_profiles(self):
            return [FakeProfile()]

    monkeypatch.setattr(api, "get_monitoring_state_repository", lambda: FakeRepo())
    client = TestClient(api.app)
    response = client.get("/animals")

    assert response.status_code == 200
    assert response.json() == [
        {
            "animal_id": "raku",
            "animal_name": "Raku",
            "expected_species": "Betta splendens",
            "active": True,
        }
    ]


def test_root_index_serves_html():
    client = TestClient(api.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_demo_video_handles_missing_safely():
    client = TestClient(api.app)
    response = client.get("/demo-video/non_existent_video_file.mp4")
    assert response.status_code == 404
    assert response.json()["detail"] == "Demo video not available."


def test_camera_preview_endpoint_is_narrow_and_does_not_invoke_monitoring(monkeypatch):
    jpeg = b"\xff\xd8preview\xff\xd9"
    monkeypatch.setattr(api, "capture_local_camera_preview", lambda index: jpeg if index == 1 else (_ for _ in ()).throw(AssertionError("unexpected index")))
    monkeypatch.setattr(api, "is_usable_jpeg_bytes", lambda value: value == jpeg)
    monkeypatch.setattr(api, "monitor_next_window", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not monitor")))
    monkeypatch.setattr(api, "get_monitoring_state_repository", lambda: (_ for _ in ()).throw(AssertionError("must not load or mutate profile state")))
    client = TestClient(api.app)

    response = client.post("/monitoring/camera-preview", json={"camera_index": 1})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.content == jpeg
    assert client.post("/monitoring/camera-preview", json={"camera_index": "1"}).status_code == 422


def test_camera_preview_unavailable_is_controlled(monkeypatch):
    def unavailable(_index):
        raise api.CameraCaptureError("private camera detail")

    monkeypatch.setattr(api, "capture_local_camera_preview", unavailable)
    response = TestClient(api.app).post("/monitoring/camera-preview", json={"camera_index": 0})

    assert response.status_code == 503
    assert response.json() == {"detail": "Camera preview is unavailable. Check the local camera and try again."}


def test_camera_preview_endpoint_returns_jpeg_after_one_internal_capture_retry(monkeypatch):
    class Capture:
        def __init__(self, frames, opened=True):
            self.frames = iter(frames)
            self.opened = opened
            self.released = False

        def isOpened(self):
            return self.opened

        def read(self):
            try:
                return True, next(self.frames)
            except StopIteration:
                return False, None

        def release(self):
            self.released = True

    class Frame:
        size = 1

        def max(self):
            return 48

    class Cv2:
        def __init__(self):
            self.captures = iter([Capture([], opened=False), Capture([Frame()] * 4)])

        def VideoCapture(self, _index):
            return next(self.captures)

        def imencode(self, _extension, _frame):
            class Encoded:
                def tobytes(self):
                    return b"\xff\xd8preview\xff\xd9"

            return True, Encoded()

    service = VideoMonitoringService(cv2_module=Cv2())
    jpeg = b"\xff\xd8preview\xff\xd9"
    monkeypatch.setattr(api, "capture_local_camera_preview", lambda index: service.capture_webcam_snapshot(index))
    monkeypatch.setattr(api, "is_usable_jpeg_bytes", lambda value: value == jpeg)

    response = TestClient(api.app).post("/monitoring/camera-preview", json={"camera_index": 1})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.content == jpeg


def test_camera_preview_rejects_empty_or_invalid_jpeg_even_when_capture_returns(monkeypatch):
    monkeypatch.setattr(api, "capture_local_camera_preview", lambda _index: b"\xff\xd8not-decodable\xff\xd9")

    response = TestClient(api.app).post("/monitoring/camera-preview", json={"camera_index": 0})

    assert response.status_code == 503
    assert response.json() == {"detail": "Camera preview is unavailable. Check the local camera and try again."}
