"""Stateful tools that make Comfort-z a monitoring agent, not a chat wrapper."""
from comfort_z.models import MonitorResult, Severity, StoredObservation
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
    repository.save(current)
    decision = decide_monitoring(current, prior)
    result = MonitorResult(observation=current, decision=decision, history_count=len(prior))
    return result.model_dump(mode="json")

def get_recent_observations(animal_id: str, limit: int = 5) -> list[dict]:
    """Retrieve recent saved observations for one animal, newest first."""
    observations = get_repository().recent_for_animal(animal_id.strip(), limit=max(1, min(limit, 20)))
    return [item.model_dump(mode="json") for item in observations]
