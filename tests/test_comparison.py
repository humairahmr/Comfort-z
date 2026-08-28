from comfort_z.models import (
    GeminiObservation,
    ObservationStatus,
    Severity,
    StoredObservation,
    Trend,
)
from comfort_z.services.comparison import decide_monitoring

def observation(
    severity: Severity,
    animal_visible: bool = True,
    status: ObservationStatus = ObservationStatus.VALID,
) -> StoredObservation:
    visual = GeminiObservation(
        posture="lying down",
        activity_level="low",
        apparent_movement="still",
        confidence=0.7,
        behavioral_interpretation="Visible behaviour requires follow-up.",
        uncertainty="A still image cannot show duration.",
        severity=severity,
        animal_visible=animal_visible,
        observation_status=status,
    )
    return StoredObservation(animal_id="milo", gemini_observation=visual, severity=severity, explanation=visual.behavioral_interpretation)

def test_first_observation_is_saved_for_monitoring_not_alerted():
    decision = decide_monitoring(observation(Severity.CONCERNING), [])
    assert not decision.alert_status
    assert decision.trend == Trend.FIRST_OBSERVATION

def test_worsening_observation_creates_alert():
    decision = decide_monitoring(observation(Severity.CONCERNING), [observation(Severity.MONITOR)])
    assert decision.alert_status
    assert decision.trend == Trend.WORSENING


def test_normal_to_monitor_is_worsening_not_unchanged():
    decision = decide_monitoring(observation(Severity.MONITOR), [observation(Severity.NORMAL)])
    assert not decision.alert_status
    assert decision.trend == Trend.WORSENING

def test_repeated_concerning_observations_create_alert():
    decision = decide_monitoring(observation(Severity.CONCERNING), [observation(Severity.CONCERNING)])
    assert decision.alert_status
    assert decision.trend == Trend.PERSISTING


def test_animal_not_visible_is_excluded_from_decisions():
    invisible = observation(
        Severity.NORMAL,
        animal_visible=False,
        status=ObservationStatus.ANIMAL_NOT_VISIBLE,
    )
    decision = decide_monitoring(invisible, [observation(Severity.CONCERNING)])
    assert decision.severity == Severity.MONITOR
    assert decision.trend == Trend.INSUFFICIENT_VISIBILITY
    assert not decision.alert_status


def test_invalid_prior_frame_is_excluded_from_next_trend():
    invisible = observation(
        Severity.MONITOR,
        animal_visible=False,
        status=ObservationStatus.UNCERTAIN,
    )
    decision = decide_monitoring(
        observation(Severity.NORMAL),
        [invisible, observation(Severity.NORMAL)],
    )
    assert decision.trend == Trend.UNCHANGED
