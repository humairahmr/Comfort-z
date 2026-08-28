"""Stateful tools that make Comfort-z a monitoring agent, not a chat wrapper."""
from comfort_z.models import MonitoringProfile, MonitorResult, Severity, StoredObservation
from comfort_z.services.analyzer import GeminiVisualAnalyzer
from comfort_z.services.comparison import decide_monitoring
from comfort_z.services.repository import get_repository

def monitor_animal(
    animal_id: str,
    image_path: str,
    source_info: str | None = None,
    animal_name: str | None = None,
    expected_species: str | None = None,
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
    )
    decision = decide_monitoring(current, prior)
    current = current.model_copy(
        update={"alert_status": decision.alert_status, "trend": decision.trend}
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
    source_reference: str | int,
    source_type: str,
    normal_sampling_interval_seconds: float = 300.0,
    elevated_sampling_interval_seconds: float = 60.0,
    daily_sample_budget: int = 24,
    animal_name: str | None = None,
    expected_species: str | None = None,
    report_time: str = "08:00",
    timezone: str = "UTC",
) -> dict:
    """Save a persistent goal such as 'Keep an eye on Raku.' without starting a loop."""
    from comfort_z.services.orchestration import create_or_update_monitoring_profile

    profile = MonitoringProfile(
        animal_id=animal_id.strip(),
        animal_name=animal_name,
        expected_species=expected_species,
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
