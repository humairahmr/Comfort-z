from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from comfort_z.models import (
    DailyReportNarrative,
    DirectEnvironmentReading,
    GeminiObservation,
    MonitoringProfile,
    MonitoringSourceType,
    OwnerUpdate,
    OwnerUpdateCategory,
    Severity,
    StoredObservation,
    VideoMonitoringSession,
)
from comfort_z.services.orchestration import (
    MonitoringProfileNotFoundError,
    generate_daily_report,
    monitor_next_window,
    record_owner_update,
)
from comfort_z.services.repository import (
    FirestoreMonitoringStateRepository,
    LocalJsonMonitoringStateRepository,
)
from comfort_z.services.comparison import decide_monitoring


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def profile(**updates):
    values = {
        "animal_id": "raku",
        "animal_name": "Raku",
        "expected_species": "Betta splendens",
        "monitoring_goal": "Keep an eye on Raku.",
        "source_reference": "Raku.mp4",
        "source_type": MonitoringSourceType.VIDEO,
        "normal_sampling_interval_seconds": 300,
        "elevated_sampling_interval_seconds": 60,
        "daily_sample_budget": 24,
        "budget_period_date": date(2026, 8, 30),
    }
    values.update(updates)
    return MonitoringProfile(**values)


def update(**updates):
    values = {
        "animal_id": "raku",
        "category": OwnerUpdateCategory.FEEDING,
        "note": "Fed Raku at 8 PM.",
        "occurred_at": NOW,
    }
    values.update(updates)
    return OwnerUpdate(**values)


def test_owner_update_validation_keeps_measurements_separate_from_notes():
    measurement = update(
        category=OwnerUpdateCategory.MEASUREMENT,
        note=None,
        reading=DirectEnvironmentReading(reading_type="water temperature", value=27, unit="C"),
    )

    assert measurement.reading.value == 27
    assert measurement.input_method == "typed"
    with pytest.raises(ValidationError):
        update(category=OwnerUpdateCategory.MEASUREMENT, note=None, reading=None)
    with pytest.raises(ValidationError):
        update(reading=DirectEnvironmentReading(reading_type="water temperature", value=27, unit="C"))
    with pytest.raises(ValidationError):
        update(note="   ")


def test_local_owner_updates_are_backward_compatible_and_bounded(tmp_path):
    path = tmp_path / "monitoring_state.json"
    path.write_text('{"profiles": {}, "reports": []}', encoding="utf-8")
    repository = LocalJsonMonitoringStateRepository(path)
    older = update(occurred_at=NOW - timedelta(days=1), note="Fed earlier.")
    newer = update(occurred_at=NOW, note="Fed now.")

    repository.save_owner_update(older)
    repository.save_owner_update(newer)

    assert [item.owner_update_id for item in repository.recent_owner_updates("raku", limit=1)] == [
        newer.owner_update_id
    ]
    assert [item.owner_update_id for item in repository.owner_updates_for_period(
        "raku", NOW - timedelta(hours=2), NOW + timedelta(hours=1), limit=8
    )] == [newer.owner_update_id]
    assert "owner_updates" in repository._read()


def test_owner_updates_work_for_source_less_profiles_without_mutating_monitoring_state(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    saved_profile = profile(
        source_reference=None,
        source_type=None,
        source_cursor_seconds=13,
        samples_used_in_current_period=2,
    )
    repository.save_profile(saved_profile)

    saved = record_owner_update(update(), state_repository=repository)
    loaded = repository.get_profile("raku")

    assert saved.animal_id == "raku"
    assert repository.recent_owner_updates("raku")[0].owner_update_id == saved.owner_update_id
    assert loaded.source_cursor_seconds == 13
    assert loaded.samples_used_in_current_period == 2
    assert loaded.last_monitoring_run is None


def test_unknown_animal_cannot_receive_owner_update(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")

    with pytest.raises(MonitoringProfileNotFoundError):
        record_owner_update(update(), state_repository=repository)
    assert repository.recent_owner_updates("raku") == []


def test_owner_notes_do_not_independently_change_visual_decisions():
    visual = GeminiObservation(
        animal_visible=True,
        observation_status="valid",
        posture="swimming",
        activity_level="moderate",
        apparent_movement="moving",
        confidence=0.9,
        behavioral_interpretation="The expected animal is visible.",
        uncertainty="One frame.",
        severity=Severity.NORMAL,
    )
    baseline = StoredObservation(
        animal_id="raku",
        gemini_observation=visual,
        severity=Severity.NORMAL,
        explanation=visual.behavioral_interpretation,
    )
    with_owner_note = baseline.model_copy(update={"owner_update_ids": [update().owner_update_id]})

    assert decide_monitoring(with_owner_note, []) == decide_monitoring(baseline, [])


class RecordingVideoService:
    def __init__(self):
        self.calls = []

    def monitor(self, **kwargs):
        self.calls.append(kwargs)
        return VideoMonitoringSession(
            animal_id="raku",
            source="Raku.mp4",
            attempted_samples=1,
            ended_reason="max_samples_reached",
            last_attempt_source_timestamp_seconds=1,
        )


class NoWeatherProvider:
    def get_current_context(self, **_kwargs):
        raise AssertionError("weather must not be needed for a direct reading")


def test_monitoring_receives_bounded_owner_context_and_readings_without_weather(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile(latitude=None, longitude=None))
    measurement = update(
        category=OwnerUpdateCategory.MEASUREMENT,
        note=None,
        reading=DirectEnvironmentReading(reading_type="water temperature", value=27, unit="C"),
    )
    repository.save_owner_update(measurement)
    for index in range(10):
        repository.save_owner_update(
            update(occurred_at=NOW - timedelta(minutes=index + 1), note=f"Fed {index}.")
        )
    video = RecordingVideoService()

    monitor_next_window(
        "raku",
        state_repository=repository,
        video_service=video,
        environment_provider=NoWeatherProvider(),
        now=NOW,
    )

    assert len(video.calls[0]["owner_updates"]) == 8
    assert video.calls[0]["environment_context"] is None
    assert any(reading.value == 27 for reading in video.calls[0]["direct_environment_readings"])


class CapturingReportGenerator:
    def __init__(self):
        self.history = None

    def generate(self, structured_history):
        self.history = structured_history
        return DailyReportNarrative(
            overall_activity_behavior="No valid visual observations were saved.",
            visibility_data_quality_limitations="No visual observations were available.",
            comparison_with_prior_observations="No prior valid observations were available.",
            recommended_action="Continue monitoring.",
            owner_reported_context=["Owner reported feeding at 8 PM."],
        )


class EmptyObservationRepository:
    def history_for_animal(self, _animal_id):
        return []


def test_daily_report_uses_owner_context_as_separate_bounded_input(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile())
    owner_update = update(occurred_at=NOW - timedelta(hours=5))
    repository.save_owner_update(owner_update)
    generator = CapturingReportGenerator()

    report = generate_daily_report(
        "raku",
        state_repository=repository,
        observation_repository=EmptyObservationRepository(),
        report_generator=generator,
        now=NOW,
    )

    assert generator.history["owner_reported_context"][0]["source"] == "owner"
    assert report.owner_update_ids == [owner_update.owner_update_id]
    assert report.narrative.owner_reported_context == ["Owner reported feeding at 8 PM."]


class FakeDocument:
    def __init__(self):
        self.children = {}
        self.saved = None

    def collection(self, name):
        return self.children.setdefault(name, FakeCollection())

    def set(self, payload, merge=False):
        self.saved = (payload, merge)


class FakeCollection:
    def __init__(self):
        self.documents = {}

    def document(self, name):
        return self.documents.setdefault(name, FakeDocument())


def test_firestore_owner_update_uses_animal_subcollection_without_credentials():
    repository = FirestoreMonitoringStateRepository.__new__(FirestoreMonitoringStateRepository)
    repository.animals = FakeCollection()
    repository._firestore = SimpleNamespace(Query=SimpleNamespace(DESCENDING="DESCENDING"))
    owner_update = update()

    repository.save_owner_update(owner_update)

    saved = repository.animals.document("raku").collection("owner_updates").document(
        owner_update.owner_update_id
    ).saved
    assert saved[0]["owner_update_id"] == owner_update.owner_update_id
    assert saved[1] is False
