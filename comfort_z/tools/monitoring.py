"""Stateful tools that make Comfort-z a monitoring agent, not a chat wrapper."""
from comfort_z.models import (
    DirectEnvironmentReading,
    EnvironmentContext,
    MonitoringProfile,
    MonitorResult,
    OwnerUpdate,
    Severity,
    StoredObservation,
)
from comfort_z.services.analyzer import GeminiVisualAnalyzer
from comfort_z.services.comparison import decide_monitoring
from comfort_z.services.environment import missing_direct_reading_requests
from comfort_z.services.repository import get_repository
from comfort_z.services.research import get_research_provider, maybe_research

def monitor_animal(
    animal_id: str,
    image_path: str,
    source_info: str | None = None,
    animal_name: str | None = None,
    expected_species: str | None = None,
    environment_context: EnvironmentContext | None = None,
    direct_environment_readings: list[DirectEnvironmentReading] | None = None,
    owner_updates: list[OwnerUpdate] | None = None,
    enclosure_type: str | None = None,
) -> dict:
    """Analyze, save, compare, and decide whether a visual observation needs an alert.

    Args:
        animal_id: Stable owner-provided name or ID, for example "milo".
        image_path: Image or Gemini-supported short visual-file path accessible to this process.
        source_info: Optional provenance, such as a video frame number and timestamp.
        animal_name: Optional owner-facing name for the monitored animal.
        expected_species: Optional known species used to determine whether the right animal is visible.
    """
    animal_id = animal_id.strip()
    if not animal_id:
        raise ValueError("animal_id cannot be empty.")
    repository = get_repository()
    prior = repository.recent_for_animal(animal_id, limit=5)
    visual = GeminiVisualAnalyzer().analyze_file(
        image_path,
        expected_species=expected_species,
        environment_context=environment_context,
        direct_environment_readings=direct_environment_readings,
        owner_updates=owner_updates,
    )
    if not visual.animal_visible or visual.observation_status.value != "valid":
        visual = visual.model_copy(update={"severity": Severity.MONITOR})
    current = StoredObservation(
        animal_id=animal_id,
        animal_name=animal_name,
        expected_species=expected_species,
        gemini_observation=visual,
        severity=visual.severity,
        explanation=visual.behavioral_interpretation,
        source_info=source_info,
        environment_context=environment_context,
        direct_environment_readings=direct_environment_readings or [],
        owner_update_ids=[update.owner_update_id for update in owner_updates or []],
        missing_direct_reading_requests=missing_direct_reading_requests(
            environment_context, direct_environment_readings or [], enclosure_type
        ),
    )
    decision = decide_monitoring(current, prior)
    research_context = maybe_research(
        current,
        prior,
        trend=decision.trend,
        alert_status=decision.alert_status,
        provider=get_research_provider(),
        owner_updates=owner_updates,
    )
    current = current.model_copy(
        update={
            "alert_status": decision.alert_status,
            "trend": decision.trend,
            "research_context": research_context,
        }
    )
    repository.save(current)
    result = MonitorResult(observation=current, decision=decision, history_count=len(prior))
    return result.model_dump(mode="json")

def get_recent_observations(animal_id: str, limit: int = 5) -> list[dict]:
    """Retrieve recent saved observations for one animal, newest first."""
    observations = get_repository().recent_for_animal(animal_id.strip(), limit=max(1, min(limit, 20)))
    return [item.model_dump(mode="json") for item in observations]


def create_monitoring_profile(
    animal_id: str,
    monitoring_goal: str,
    source_reference: str | int | None = None,
    source_type: str | None = None,
    normal_sampling_interval_seconds: float = 300.0,
    elevated_sampling_interval_seconds: float = 60.0,
    daily_sample_budget: int = 24,
    animal_name: str | None = None,
    expected_species: str | None = None,
    location_name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    enclosure_type: str | None = None,
    direct_environment_readings: list[DirectEnvironmentReading] | None = None,
    report_time: str = "08:00",
    timezone: str = "UTC",
) -> dict:
    """Save a persistent goal such as 'Keep an eye on Raku.' without starting a loop."""
    from comfort_z.services.orchestration import create_or_update_monitoring_profile

    profile = MonitoringProfile(
        animal_id=animal_id.strip(),
        animal_name=animal_name,
        expected_species=expected_species,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        enclosure_type=enclosure_type,
        direct_environment_readings=direct_environment_readings or [],
        monitoring_goal=monitoring_goal,
        source_reference=source_reference,
        source_type=source_type,
        normal_sampling_interval_seconds=normal_sampling_interval_seconds,
        elevated_sampling_interval_seconds=elevated_sampling_interval_seconds,
        daily_sample_budget=daily_sample_budget,
        report_time=report_time,
        timezone=timezone,
    )
    return create_or_update_monitoring_profile(profile).model_dump(mode="json")


def connect_monitoring_source(
    animal_id: str, source_reference: str | int, source_type: str, source_display_name: str | None = None
) -> dict:
    """Attach one existing video or local-camera source, initially paused."""
    from comfort_z.services.orchestration import connect_monitoring_source as connect_source

    return connect_source(
        animal_id.strip(), source_reference=source_reference, source_type=source_type,
        source_display_name=source_display_name,
    ).model_dump(mode="json")


def disconnect_monitoring_source(animal_id: str) -> dict:
    """Detach the configured source while preserving monitoring history."""
    from comfort_z.services.orchestration import disconnect_monitoring_source as disconnect_source

    return disconnect_source(animal_id.strip()).model_dump(mode="json")


def start_monitoring(animal_id: str) -> dict:
    """Enable future bounded monitoring windows for a configured source."""
    from comfort_z.services.orchestration import start_monitoring as start_profile

    return start_profile(animal_id.strip()).model_dump(mode="json")


def pause_monitoring(animal_id: str) -> dict:
    """Pause future bounded monitoring windows without disconnecting the source."""
    from comfort_z.services.orchestration import pause_monitoring as pause_profile

    return pause_profile(animal_id.strip()).model_dump(mode="json")


def capture_local_camera_preview(camera_index: int) -> bytes:
    """Capture one local snapshot without starting a monitoring workflow."""
    from comfort_z.services.video import VideoMonitoringService

    return VideoMonitoringService().capture_webcam_snapshot(camera_index)


def set_profile_photo_reference(animal_id: str, profile_photo_reference: str) -> dict:
    """Attach one owner-selected profile photo without invoking monitoring."""
    from comfort_z.services.orchestration import set_profile_photo_reference as set_photo

    return set_photo(animal_id.strip(), profile_photo_reference).model_dump(mode="json")


def monitor_next_window(animal_id: str, window_max_samples: int = 2) -> dict:
    """Run only the next bounded source window for a saved monitoring profile."""
    from comfort_z.services.orchestration import monitor_next_window as run_next_window

    return run_next_window(
        animal_id.strip(), window_max_samples=window_max_samples
    ).model_dump(mode="json")


def generate_daily_report(animal_id: str) -> dict:
    """Summarize the prior configured monitoring period from structured history only."""
    from comfort_z.services.orchestration import generate_daily_report as run_daily_report

    return run_daily_report(animal_id.strip()).model_dump(mode="json")


def get_recent_daily_reports(animal_id: str, limit: int = 5) -> list[dict]:
    """Retrieve persisted daily reports for an animal, newest first."""
    from comfort_z.services.orchestration import get_recent_daily_reports as load_reports

    return [
        report.model_dump(mode="json")
        for report in load_reports(animal_id.strip(), limit=max(1, min(limit, 20)))
    ]


def record_owner_update(
    animal_id: str,
    category: str,
    occurred_at=None,
    note: str | None = None,
    reading: DirectEnvironmentReading | None = None,
    input_method: str = "typed",
) -> dict:
    """Persist one owner-provided update without invoking monitoring or Gemini."""
    from comfort_z.models import OwnerUpdate
    from comfort_z.services.orchestration import record_owner_update as save_owner_update

    values = {
        "animal_id": animal_id.strip(),
        "category": category,
        "note": note,
        "reading": reading,
        "input_method": input_method,
    }
    if occurred_at is not None:
        values["occurred_at"] = occurred_at
    update = OwnerUpdate(**values)
    return save_owner_update(update).model_dump(mode="json")


def get_recent_owner_updates(animal_id: str, limit: int = 20) -> list[dict]:
    """Retrieve owner-provided updates without turning them into observations."""
    from comfort_z.services.orchestration import get_recent_owner_updates as load_owner_updates

    return [
        update.model_dump(mode="json")
        for update in load_owner_updates(animal_id.strip(), limit=max(1, min(limit, 50)))
    ]
