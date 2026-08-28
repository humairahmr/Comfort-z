"""Small, explainable rules for cross-observation monitoring."""
from comfort_z.models import MonitoringDecision, Severity, StoredObservation, Trend
_RANK = {Severity.NORMAL: 0, Severity.MONITOR: 1, Severity.CONCERNING: 2}

def decide_monitoring(current: StoredObservation, prior: list[StoredObservation]) -> MonitoringDecision:
    if not prior:
        return MonitoringDecision(alert_status=False, severity=current.severity, trend=Trend.FIRST_OBSERVATION, reason="This is the first saved observation, so Comfort-z has recorded a baseline and recommends monitoring for change.", supporting_observation_ids=[current.observation_id], recommended_action="Continue monitoring and submit another clear observation if behaviour continues or changes.")
    latest, recent = prior[0], [current, *prior[:2]]
    concerning = [item for item in recent if item.severity == Severity.CONCERNING]
    support = [item.observation_id for item in recent]
    if current.severity == Severity.CONCERNING and _RANK[current.severity] > _RANK[latest.severity]:
        return MonitoringDecision(alert_status=True, severity=Severity.CONCERNING, trend=Trend.WORSENING, reason="The latest visible observation is potentially concerning and is more severe than the preceding saved observation.", supporting_observation_ids=support, recommended_action="Seek professional veterinary advice, especially if the visible change continues or the animal seems distressed.")
    if len(concerning) >= 2:
        return MonitoringDecision(alert_status=True, severity=Severity.CONCERNING, trend=Trend.PERSISTING, reason="Potentially concerning visible signs appear in at least two of the latest three observations.", supporting_observation_ids=[item.observation_id for item in concerning], recommended_action="Seek professional veterinary advice and continue recording clear observations.")
    if _RANK[current.severity] < _RANK[latest.severity]:
        return MonitoringDecision(alert_status=False, severity=current.severity, trend=Trend.IMPROVING, reason="The latest observation appears less concerning than the preceding saved observation.", supporting_observation_ids=support, recommended_action="Continue monitoring; improvement in one observation does not rule out a problem.")
    return MonitoringDecision(alert_status=False, severity=current.severity, trend=Trend.UNCHANGED, reason="The latest visible observation does not show a clear severity change from the preceding record.", supporting_observation_ids=support, recommended_action="Continue monitoring and submit another observation if behaviour changes.")
