from comfort_z.models import GeminiObservation, Severity, StoredObservation, Trend
from comfort_z.services.comparison import decide_monitoring

def observation(severity: Severity) -> StoredObservation:
    visual = GeminiObservation(posture="lying down", activity_level="low", apparent_movement="still", confidence=0.7, behavioral_interpretation="Visible behaviour requires follow-up.", uncertainty="A still image cannot show duration.", severity=severity)
    return StoredObservation(animal_id="milo", gemini_observation=visual, severity=severity, explanation=visual.behavioral_interpretation)

def test_first_observation_is_saved_for_monitoring_not_alerted():
    decision = decide_monitoring(observation(Severity.CONCERNING), [])
    assert not decision.alert_status
    assert decision.trend == Trend.FIRST_OBSERVATION

def test_worsening_observation_creates_alert():
    decision = decide_monitoring(observation(Severity.CONCERNING), [observation(Severity.MONITOR)])
    assert decision.alert_status
    assert decision.trend == Trend.WORSENING

def test_repeated_concerning_observations_create_alert():
    decision = decide_monitoring(observation(Severity.CONCERNING), [observation(Severity.CONCERNING)])
    assert decision.alert_status
    assert decision.trend == Trend.PERSISTING
