from fastapi.testclient import TestClient

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
