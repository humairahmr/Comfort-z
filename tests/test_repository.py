from datetime import datetime, timezone
from comfort_z.models import GeminiObservation, ObservationStatus, Severity, StoredObservation
from comfort_z.services.repository import LocalJsonObservationRepository

def make_observation(animal_id: str) -> StoredObservation:
    visual = GeminiObservation(posture="standing", activity_level="moderate", apparent_movement="walking", confidence=0.8, behavioral_interpretation="The animal appears alert in this image.", uncertainty="Only one still image was provided.", severity=Severity.NORMAL, animal_visible=True, observation_status=ObservationStatus.VALID)
    return StoredObservation(animal_id=animal_id, timestamp=datetime.now(timezone.utc), gemini_observation=visual, severity=Severity.NORMAL, explanation=visual.behavioral_interpretation)

def test_local_repository_stores_and_filters_history(tmp_path):
    repository = LocalJsonObservationRepository(tmp_path / "observations.json")
    first = repository.save(make_observation("milo"))
    repository.save(make_observation("luna"))
    second = repository.save(make_observation("milo"))
    history = repository.recent_for_animal("milo")
    assert [item.observation_id for item in history] == [second.observation_id, first.observation_id]


def test_local_monitoring_state_repository_list_profiles(tmp_path):
    from comfort_z.models import MonitoringProfile, MonitoringSourceType
    from comfort_z.services.repository import LocalJsonMonitoringStateRepository

    repository = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    assert repository.list_profiles() == []

    profile = MonitoringProfile(
        animal_id="raku",
        animal_name="Raku",
        expected_species="Betta splendens",
        monitoring_goal="Keep an eye on Raku.",
        source_reference="raku.mp4",
        source_type=MonitoringSourceType.VIDEO,
        normal_sampling_interval_seconds=300,
        elevated_sampling_interval_seconds=60,
        daily_sample_budget=24,
    )
    repository.save_profile(profile)
    profiles = repository.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].animal_id == "raku"

