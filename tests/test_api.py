from fastapi.testclient import TestClient
import pytest

from comfort_z import api


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
