from datetime import datetime, timezone

from comfort_z.models import EnvironmentContext, GeminiObservation, ObservationStatus, Severity
from comfort_z.tools import monitoring


class MemoryRepository:
    def __init__(self):
        self.saved = []

    def recent_for_animal(self, _animal_id, limit=5):
        return self.saved[-limit:][::-1]

    def save(self, observation):
        self.saved.append(observation)
        return observation


class FakeAnalyzer:
    def analyze_file(self, *_args, **_kwargs):
        return GeminiObservation(
            animal_visible=True,
            observation_status=ObservationStatus.VALID,
            posture="resting",
            activity_level="low",
            apparent_movement="still",
            confidence=0.8,
            behavioral_interpretation="The animal is visible.",
            uncertainty="One frame.",
            severity=Severity.NORMAL,
        )


def test_environment_context_and_missing_direct_reading_are_persisted(monkeypatch):
    repository = MemoryRepository()
    monkeypatch.setattr(monitoring, "get_repository", lambda: repository)
    monkeypatch.setattr(monitoring, "GeminiVisualAnalyzer", FakeAnalyzer)
    context = EnvironmentContext(
        provider="test-weather",
        outdoor_temperature_c=33,
        observed_at=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
    )

    result = monitoring.monitor_animal(
        "animal-1",
        "unused.jpg",
        environment_context=context,
        enclosure_type="enclosure",
    )

    observation = result["observation"]
    assert observation["environment_context"]["outdoor_temperature_c"] == 33
    assert observation["missing_direct_reading_requests"] == [
        "Outdoor conditions are hot, but the actual enclosure temperature is unknown. "
        "Ask the owner for a direct temperature reading."
    ]
    assert repository.saved[0].environment_context == context
