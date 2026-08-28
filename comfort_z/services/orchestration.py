"""Finite continuous-monitoring operations composed from validated Comfort-z services."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from comfort_z.models import (
    DailyMonitoringReport,
    DailyReportNarrative,
    MonitoringProfile,
    MonitoringWindowResult,
    ObservationStatus,
    SamplingMode,
)
from comfort_z.services.analyzer import GeminiDailyReportGenerator
from comfort_z.services.comparison import is_valid_animal_observation
from comfort_z.services.repository import (
    MonitoringStateRepository,
    ObservationRepository,
    get_monitoring_state_repository,
    get_repository,
)
from comfort_z.services.video import VideoMonitoringService

DEFAULT_WINDOW_MAX_SAMPLES = 2
MAX_WINDOW_MAX_SAMPLES = 10


class DailyReportGenerator(Protocol):
    def generate(self, structured_history: dict) -> DailyReportNarrative:
        """Generate a report from structured records, never raw images."""


def create_or_update_monitoring_profile(
    profile: MonitoringProfile,
    *,
    state_repository: MonitoringStateRepository | None = None,
    now: datetime | None = None,
) -> MonitoringProfile:
    """Persist a user goal such as 'Keep an eye on Raku.'"""
    repository = state_repository or get_monitoring_state_repository()
    timestamp = now or datetime.now(timezone.utc)
    existing = repository.get_profile(profile.animal_id)
    saved = profile.model_copy(
        update={
            "created_at": existing.created_at if existing else profile.created_at,
            "updated_at": timestamp,
        }
    )
    return repository.save_profile(saved)


def monitor_next_window(
    animal_id: str,
    *,
    window_max_samples: int = DEFAULT_WINDOW_MAX_SAMPLES,
    state_repository: MonitoringStateRepository | None = None,
    video_service: VideoMonitoringService | None = None,
    now: datetime | None = None,
) -> MonitoringWindowResult:
    """Process one finite source window and save its resume cursor and quota state."""
    if not 1 <= window_max_samples <= MAX_WINDOW_MAX_SAMPLES:
        raise ValueError(
            f"window_max_samples must be between 1 and {MAX_WINDOW_MAX_SAMPLES}."
        )
    state = state_repository or get_monitoring_state_repository()
    profile = state.get_profile(animal_id.strip())
    if profile is None:
        raise ValueError(f"No monitoring profile exists for animal {animal_id!r}.")

    timestamp = now or datetime.now(timezone.utc)
    profile = _reset_daily_budget_if_needed(profile, timestamp)
    remaining = max(0, profile.daily_sample_budget - profile.samples_used_in_current_period)
    if not profile.active:
        return _window_result(profile, "inactive", remaining)
    if remaining == 0:
        updated = profile.model_copy(update={"last_monitoring_run": timestamp, "updated_at": timestamp})
        state.save_profile(updated)
        return _window_result(updated, "daily_budget_exhausted", 0)

    interval = (
        profile.elevated_sampling_interval_seconds
        if profile.current_sampling_mode == SamplingMode.ELEVATED
        else profile.normal_sampling_interval_seconds
    )
    service = video_service or VideoMonitoringService()
    session = service.monitor(
        animal_id=profile.animal_id,
        source=profile.source_reference,
        sample_interval_seconds=interval,
        max_samples=min(window_max_samples, remaining),
        animal_name=profile.animal_name,
        expected_species=profile.expected_species,
        start_at_seconds=profile.source_cursor_seconds,
    )

    cursor = profile.source_cursor_seconds
    if session.last_attempt_source_timestamp_seconds is not None:
        # The tiny advance avoids sampling the same decoded video frame twice.
        cursor = max(cursor, session.last_attempt_source_timestamp_seconds + 0.001)
    active = profile.active
    if profile.source_type.value == "video" and session.attempted_samples == 0 and session.ended_reason == "completed":
        active = False

    updated = profile.model_copy(
        update={
            "source_cursor_seconds": cursor,
            "samples_used_in_current_period": profile.samples_used_in_current_period
            + session.attempted_samples,
            "current_sampling_mode": _next_sampling_mode(profile, session),
            "active": active,
            "last_monitoring_run": timestamp,
            "updated_at": timestamp,
        }
    )
    state.save_profile(updated)
    remaining = max(0, updated.daily_sample_budget - updated.samples_used_in_current_period)
    return _window_result(updated, session.ended_reason, remaining, session)


def generate_daily_report(
    animal_id: str,
    *,
    state_repository: MonitoringStateRepository | None = None,
    observation_repository: ObservationRepository | None = None,
    report_generator: DailyReportGenerator | None = None,
    now: datetime | None = None,
) -> DailyMonitoringReport:
    """Generate and persist one daily report from structured saved observations only."""
    state = state_repository or get_monitoring_state_repository()
    profile = state.get_profile(animal_id.strip())
    if profile is None:
        raise ValueError(f"No monitoring profile exists for animal {animal_id!r}.")
    timestamp = now or datetime.now(timezone.utc)
    period_start, period_end = _reporting_period(profile, timestamp)
    observation_store = observation_repository or get_repository()
    full_history = observation_store.history_for_animal(profile.animal_id)
    observations = [
        observation
        for observation in full_history
        if period_start <= observation.timestamp <= period_end
    ]
    valid = [item for item in observations if is_valid_animal_observation(item)]
    not_visible = [
        item
        for item in observations
        if item.gemini_observation.observation_status == ObservationStatus.ANIMAL_NOT_VISIBLE
    ]
    uncertain = [
        item
        for item in observations
        if item.gemini_observation.observation_status == ObservationStatus.UNCERTAIN
    ]
    concerning = [item for item in valid if item.severity.value == "potentially_concerning"]
    alerts = [item for item in valid if item.alert_status]
    prior_valid = [
        item
        for item in full_history
        if item.timestamp < period_start and is_valid_animal_observation(item)
    ][:3]
    structured_history = {
        "animal": {
            "animal_id": profile.animal_id,
            "animal_name": profile.animal_name,
            "expected_species": profile.expected_species,
            "monitoring_goal": profile.monitoring_goal,
        },
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "counts": {
            "valid": len(valid),
            "animal_not_visible": len(not_visible),
            "uncertain": len(uncertain),
            "concerning": len(concerning),
            "alerts": len(alerts),
        },
        # Only valid records are input to behavioural reasoning. Invalid records
        # are represented by aggregate data-quality counts, never behaviour claims.
        "valid_observations": [_observation_summary(item) for item in valid],
        "prior_valid_observations": [_observation_summary(item) for item in prior_valid],
        "concerning_observation_ids": [item.observation_id for item in concerning],
        "alert_observation_ids": [item.observation_id for item in alerts],
    }
    narrative = (report_generator or GeminiDailyReportGenerator()).generate(structured_history)
    report = DailyMonitoringReport(
        animal_id=profile.animal_id,
        animal_name=profile.animal_name,
        expected_species=profile.expected_species,
        period_start=period_start,
        period_end=period_end,
        generated_at=timestamp,
        valid_observation_count=len(valid),
        animal_not_visible_count=len(not_visible),
        uncertain_observation_count=len(uncertain),
        concerning_observation_ids=[item.observation_id for item in concerning],
        alert_observation_ids=[item.observation_id for item in alerts],
        narrative=narrative,
    )
    return state.save_report(report)


def get_recent_daily_reports(
    animal_id: str,
    limit: int = 5,
    *,
    state_repository: MonitoringStateRepository | None = None,
) -> list[DailyMonitoringReport]:
    return (state_repository or get_monitoring_state_repository()).recent_reports(
        animal_id.strip(), max(1, min(limit, 20))
    )


def _reset_daily_budget_if_needed(profile: MonitoringProfile, now: datetime) -> MonitoringProfile:
    local_date = now.astimezone(ZoneInfo(profile.timezone)).date()
    if profile.budget_period_date == local_date:
        return profile
    return profile.model_copy(
        update={"budget_period_date": local_date, "samples_used_in_current_period": 0}
    )


def _next_sampling_mode(profile: MonitoringProfile, session) -> SamplingMode:
    for sample in session.samples:
        observation = sample.monitoring_result.get("observation", {})
        visual = observation.get("gemini_observation", {})
        if (
            visual.get("animal_visible") is True
            and visual.get("observation_status") == ObservationStatus.VALID.value
            and (
                observation.get("severity") != "normal"
                or sample.monitoring_result.get("decision", {}).get("alert_status") is True
            )
        ):
            return SamplingMode.ELEVATED
    return SamplingMode.NORMAL


def _window_result(
    profile: MonitoringProfile,
    ended_reason: str,
    remaining: int,
    session=None,
) -> MonitoringWindowResult:
    return MonitoringWindowResult(
        animal_id=profile.animal_id,
        active=profile.active,
        sampling_mode=profile.current_sampling_mode,
        source_cursor_seconds=profile.source_cursor_seconds,
        samples_used_in_current_period=profile.samples_used_in_current_period,
        remaining_daily_sample_budget=remaining,
        ended_reason=ended_reason,
        session=session,
    )


def _reporting_period(profile: MonitoringProfile, now: datetime) -> tuple[datetime, datetime]:
    try:
        report_time = time.fromisoformat(profile.report_time)
    except ValueError as error:
        raise ValueError("report_time must use HH:MM or HH:MM:SS format.") from error
    zone = ZoneInfo(profile.timezone)
    local_now = now.astimezone(zone)
    local_end = datetime.combine(local_now.date(), report_time, tzinfo=zone)
    if local_now < local_end:
        local_end -= timedelta(days=1)
    return local_end.astimezone(timezone.utc) - timedelta(days=1), local_end.astimezone(timezone.utc)


def _observation_summary(observation) -> dict:
    visual = observation.gemini_observation
    return {
        "observation_id": observation.observation_id,
        "timestamp": observation.timestamp.isoformat(),
        "severity": observation.severity.value,
        "posture": visual.posture,
        "activity_level": visual.activity_level,
        "apparent_movement": visual.apparent_movement,
        "visible_abnormalities": visual.visible_abnormalities,
        "behavioral_interpretation": visual.behavioral_interpretation,
        "confidence": visual.confidence,
        "alert_status": observation.alert_status,
        "trend": observation.trend.value if observation.trend else None,
    }
