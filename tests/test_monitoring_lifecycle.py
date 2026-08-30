from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from comfort_z import api
from comfort_z.models import MonitoringProfile, MonitoringSourceType, SamplingMode
from comfort_z.services.orchestration import (
    MonitoringSourceNotConnectedError,
    connect_monitoring_source,
    disconnect_monitoring_source,
    pause_monitoring,
    start_monitoring,
)
from comfort_z.services.repository import LocalJsonMonitoringStateRepository


def profile(**updates):
    values = {
        "animal_id": "milo",
        "animal_name": "Milo",
        "expected_species": None,
        "monitoring_goal": "Keep an eye on Milo.",
        "source_reference": None,
        "source_type": None,
        "normal_sampling_interval_seconds": 300,
        "elevated_sampling_interval_seconds": 60,
        "daily_sample_budget": 24,
        "budget_period_date": date(2026, 8, 30),
    }
    values.update(updates)
    return MonitoringProfile(**values)


def test_source_less_profile_is_inactive_and_species_is_optional():
    saved = profile(active=True)

    assert saved.expected_species is None
    assert saved.active is False
    assert saved.has_monitoring_source is False


def test_webcam_requires_an_integer_reference():
    with pytest.raises(ValidationError, match="integer camera index"):
        profile(source_reference="1", source_type=MonitoringSourceType.WEBCAM)

    assert profile(source_reference=1, source_type=MonitoringSourceType.WEBCAM).has_monitoring_source


def test_connect_change_disconnect_start_and_pause_preserve_unrelated_state(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "state.json")
    original = profile(
        samples_used_in_current_period=4,
        current_sampling_mode=SamplingMode.ELEVATED,
        source_cursor_seconds=17,
        source_cursor_frame_index=45,
    )
    repository.save_profile(original)

    connected = connect_monitoring_source(
        "milo", source_reference=1, source_type=MonitoringSourceType.WEBCAM, state_repository=repository
    )
    assert connected.active is False
    assert connected.source_reference == 1
    assert connected.samples_used_in_current_period == 4
    assert connected.current_sampling_mode == SamplingMode.ELEVATED
    assert connected.source_cursor_seconds == 0
    assert connected.source_cursor_frame_index is None

    started = start_monitoring("milo", state_repository=repository)
    assert started.active is True
    paused = pause_monitoring("milo", state_repository=repository)
    assert paused.active is False
    assert paused.source_reference == 1

    disconnected = disconnect_monitoring_source("milo", state_repository=repository)
    assert disconnected.has_monitoring_source is False
    assert disconnected.active is False
    assert disconnected.source_cursor_seconds == 0
    assert disconnected.samples_used_in_current_period == 4


def test_connecting_the_same_source_keeps_its_cursor_but_pauses(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "state.json")
    repository.save_profile(profile(source_reference="milo.mp4", source_type=MonitoringSourceType.VIDEO, active=True, source_cursor_seconds=12, source_cursor_frame_index=36))

    saved = connect_monitoring_source(
        "milo", source_reference="milo.mp4", source_type=MonitoringSourceType.VIDEO, state_repository=repository
    )

    assert saved.active is False
    assert saved.source_cursor_seconds == 12
    assert saved.source_cursor_frame_index == 36


def test_start_without_a_source_is_rejected_without_running_monitoring(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "state.json")
    repository.save_profile(profile())

    with pytest.raises(MonitoringSourceNotConnectedError):
        start_monitoring("milo", state_repository=repository)

    assert repository.get_profile("milo").active is False


def test_lifecycle_api_endpoints_are_narrow_and_validate_webcams(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "connect_monitoring_source", lambda animal_id, reference, source_type: calls.append(("connect", animal_id, reference, source_type)) or {"active": False})
    monkeypatch.setattr(api, "start_monitoring", lambda animal_id: calls.append(("start", animal_id)) or {"active": True})
    monkeypatch.setattr(api, "pause_monitoring", lambda animal_id: calls.append(("pause", animal_id)) or {"active": False})
    monkeypatch.setattr(api, "disconnect_monitoring_source", lambda animal_id: calls.append(("disconnect", animal_id)) or {"active": False})
    client = TestClient(api.app)

    assert client.put("/monitoring/milo/source", json={"source_reference": 1, "source_type": "webcam"}).status_code == 200
    assert client.post("/monitoring/milo/start").status_code == 200
    assert client.post("/monitoring/milo/pause").status_code == 200
    assert client.delete("/monitoring/milo/source").status_code == 200
    assert client.put("/monitoring/milo/source", json={"source_reference": "1", "source_type": "webcam"}).status_code == 422
    assert calls == [
        ("connect", "milo", 1, "webcam"),
        ("start", "milo"),
        ("pause", "milo"),
        ("disconnect", "milo"),
    ]
