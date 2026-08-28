from datetime import datetime, timezone
from comfort_z.models import GeminiObservation, Severity, StoredObservation
from comfort_z.services.repository import LocalJsonObservationRepository

def make_observation(animal_id: str) -> StoredObservation:
    visual = GeminiObservation(posture="standing", activity_level="moderate", apparent_movement="walking", confidence=0.8, behavioral_interpretation="The animal appears alert in this image.", uncertainty="Only one still image was provided.", severity=Severity.NORMAL)
    return StoredObservation(animal_id=animal_id, timestamp=datetime.now(timezone.utc), gemini_observation=visual, severity=Severity.NORMAL, explanation=visual.behavioral_interpretation)

def test_local_repository_stores_and_filters_history(tmp_path):
    repository = LocalJsonObservationRepository(tmp_path / "observations.json")
    first = repository.save(make_observation("milo"))
    repository.save(make_observation("luna"))
    second = repository.save(make_observation("milo"))
    history = repository.recent_for_animal("milo")
    assert [item.observation_id for item in history] == [second.observation_id, first.observation_id]
