from datetime import date, datetime, timezone

from comfort_z.models import (
    DailyReportNarrative,
    GeminiObservation,
    MonitoringProfile,
    MonitoringSourceType,
    ObservationStatus,
    SamplingMode,
    Severity,
    StoredObservation,
    VideoFrameSample,
    VideoMonitoringSession,
)
from comfort_z.services.orchestration import (
    create_or_update_monitoring_profile,
    generate_daily_report,
    monitor_next_window,
)
from comfort_z.services.repository import LocalJsonMonitoringStateRepository


def profile(**updates):
    values = {
        "animal_id": "raku",
        "animal_name": "Raku",
        "expected_species": "Betta splendens",
        "monitoring_goal": "Keep an eye on Raku.",
        "source_reference": "Raku.mp4",
        "source_type": MonitoringSourceType.VIDEO,
        "normal_sampling_interval_seconds": 5,
        "elevated_sampling_interval_seconds": 1,
        "daily_sample_budget": 5,
        "budget_period_date": date(2026, 8, 28),
    }
    values.update(updates)
    return MonitoringProfile(**values)


class RecordingVideoService:
    def __init__(self, sessions):
        self.sessions = iter(sessions)
        self.calls = []

    def monitor(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.sessions)


def session(*, attempts=1, last=5.0, samples=None, ended_reason="max_samples_reached"):
    return VideoMonitoringSession(
        animal_id="raku",
        source="Raku.mp4",
        attempted_samples=attempts,
        samples=samples or [],
        ended_reason=ended_reason,
        last_attempt_source_timestamp_seconds=last,
    )


def valid_sample(severity="normal", visible=True, status="valid", alert=False):
    return VideoFrameSample(
        source="Raku.mp4",
        frame_index=1,
        source_timestamp_seconds=5,
        monitoring_result={
            "observation": {
                "severity": severity,
                "gemini_observation": {
                    "animal_visible": visible,
                    "observation_status": status,
                },
            },
            "decision": {"alert_status": alert},
        },
    )


def test_monitoring_profile_persists_locally(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    saved = create_or_update_monitoring_profile(profile(), state_repository=repository)

    loaded = repository.get_profile("raku")

    assert loaded is not None
    assert loaded.monitoring_goal == "Keep an eye on Raku."
    assert loaded.source_cursor_seconds == 0
    assert saved.created_at == loaded.created_at


def test_inactive_profile_exits_without_opening_source(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile(active=False))
    video = RecordingVideoService([])

    result = monitor_next_window("raku", state_repository=repository, video_service=video)

    assert result.ended_reason == "inactive"
    assert video.calls == []


def test_next_window_resumes_from_persisted_cursor_and_is_bounded(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile())
    video = RecordingVideoService([session(attempts=2, last=10), session(attempts=2, last=20)])

    first = monitor_next_window(
        "raku", window_max_samples=2, state_repository=repository, video_service=video
    )
    second = monitor_next_window(
        "raku", window_max_samples=2, state_repository=repository, video_service=video
    )

    assert video.calls[0]["start_at_seconds"] == 0
    assert video.calls[0]["max_samples"] == 2
    assert video.calls[1]["start_at_seconds"] == 10.001
    assert first.source_cursor_seconds == 10.001
    assert second.source_cursor_seconds == 20.001
    assert second.samples_used_in_current_period == 4


def test_daily_budget_limits_next_window_attempts_and_prevents_extra_run(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile(daily_sample_budget=4, samples_used_in_current_period=3))
    video = RecordingVideoService([session(attempts=1, last=5)])
    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

    first = monitor_next_window(
        "raku", window_max_samples=2, state_repository=repository, video_service=video, now=now
    )
    second = monitor_next_window(
        "raku", state_repository=repository, video_service=video, now=now
    )

    assert video.calls[0]["max_samples"] == 1
    assert first.remaining_daily_sample_budget == 0
    assert second.ended_reason == "daily_budget_exhausted"
    assert len(video.calls) == 1


def test_valid_concerning_result_switches_to_elevated_but_nonvisible_does_not(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile())
    video = RecordingVideoService(
        [
            session(samples=[valid_sample(severity="monitor", visible=False, status="animal_not_visible")]),
            session(samples=[valid_sample(severity="monitor")]),
            session(samples=[valid_sample(severity="normal")]),
        ]
    )

    normal = monitor_next_window("raku", state_repository=repository, video_service=video)
    elevated = monitor_next_window("raku", state_repository=repository, video_service=video)
    monitor_next_window("raku", state_repository=repository, video_service=video)

    assert normal.sampling_mode == SamplingMode.NORMAL
    assert elevated.sampling_mode == SamplingMode.ELEVATED
    assert video.calls[1]["sample_interval_seconds"] == 5
    assert video.calls[2]["sample_interval_seconds"] == 1


class MemoryObservationRepository:
    def __init__(self, observations):
        self.observations = observations

    def history_for_animal(self, animal_id):
        return [item for item in self.observations if item.animal_id == animal_id]


class CapturingReportGenerator:
    def __init__(self):
        self.payload = None

    def generate(self, structured_history):
        self.payload = structured_history
        return DailyReportNarrative(
            overall_activity_behavior="Raku was active in the valid observations.",
            notable_changes=["Activity increased."],
            concerning_observations=["One potentially concerning observation was recorded."],
            visibility_data_quality_limitations="Some frames did not clearly show Raku.",
            comparison_with_prior_observations="The latest valid observation was compared with prior valid history.",
            recommended_action="Continue monitoring.",
        )


def observation(status, *, timestamp, severity=Severity.NORMAL, alert=False):
    visual = GeminiObservation(
        animal_visible=status == ObservationStatus.VALID,
        observation_status=status,
        posture="swimming" if status == ObservationStatus.VALID else "unclear",
        activity_level="moderate" if status == ObservationStatus.VALID else "unclear",
        apparent_movement="moving" if status == ObservationStatus.VALID else "not assessable",
        confidence=0.8,
        behavioral_interpretation="Structured test observation.",
        uncertainty="One frame.",
        severity=severity,
    )
    return StoredObservation(
        animal_id="raku",
        timestamp=timestamp,
        gemini_observation=visual,
        severity=severity,
        explanation=visual.behavioral_interpretation,
        alert_status=alert,
    )


def test_daily_report_uses_only_valid_behavioral_history_and_persists(tmp_path):
    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    repository.save_profile(profile())
    report_time = datetime(2026, 8, 29, 8, 5, tzinfo=timezone.utc)
    observations = [
        observation(ObservationStatus.VALID, timestamp=datetime(2026, 8, 28, 9, tzinfo=timezone.utc)),
        observation(
            ObservationStatus.VALID,
            timestamp=datetime(2026, 8, 28, 10, tzinfo=timezone.utc),
            severity=Severity.CONCERNING,
            alert=True,
        ),
        observation(ObservationStatus.ANIMAL_NOT_VISIBLE, timestamp=datetime(2026, 8, 28, 11, tzinfo=timezone.utc)),
        observation(ObservationStatus.UNCERTAIN, timestamp=datetime(2026, 8, 28, 12, tzinfo=timezone.utc)),
    ]
    generator = CapturingReportGenerator()

    report = generate_daily_report(
        "raku",
        state_repository=repository,
        observation_repository=MemoryObservationRepository(observations),
        report_generator=generator,
        now=report_time,
    )

    assert report.valid_observation_count == 2
    assert report.animal_not_visible_count == 1
    assert report.uncertain_observation_count == 1
    assert len(generator.payload["valid_observations"]) == 2
    assert generator.payload["counts"]["animal_not_visible"] == 1
    assert len(report.concerning_observation_ids) == 1
    assert len(report.alert_observation_ids) == 1
    assert repository.recent_reports("raku")[0].report_id == report.report_id
