"""Schemas shared by Gemini, storage, and alert logic."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

class Severity(str, Enum):
    NORMAL = "normal"
    MONITOR = "monitor"
    CONCERNING = "potentially_concerning"

class Trend(str, Enum):
    FIRST_OBSERVATION = "first_observation"
    INSUFFICIENT_VISIBILITY = "insufficient_visibility"
    UNCHANGED = "unchanged"
    IMPROVING = "improving"
    WORSENING = "worsening"
    PERSISTING = "suspicious_pattern_persisting"


class ObservationStatus(str, Enum):
    VALID = "valid"
    ANIMAL_NOT_VISIBLE = "animal_not_visible"
    UNCERTAIN = "uncertain"

class GeminiObservation(BaseModel):
    species: str | None = Field(default=None, description="Species only if reasonably identifiable.")
    # Legacy records lack these fields; treat them as uncertain rather than valid.
    animal_visible: bool = False
    observation_status: ObservationStatus = ObservationStatus.UNCERTAIN
    posture: str
    activity_level: Literal["low", "moderate", "high", "unclear"]
    apparent_movement: str
    visible_abnormalities: list[str] = Field(default_factory=list)
    environmental_observations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    behavioral_interpretation: str
    uncertainty: str
    severity: Severity

class StoredObservation(BaseModel):
    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    animal_id: str
    animal_name: str | None = None
    expected_species: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    gemini_observation: GeminiObservation
    severity: Severity
    explanation: str
    source_info: str | None = None

class MonitoringDecision(BaseModel):
    alert_status: bool
    severity: Severity
    trend: Trend
    reason: str
    supporting_observation_ids: list[str] = Field(default_factory=list)
    recommended_action: str

class MonitorResult(BaseModel):
    observation: StoredObservation
    decision: MonitoringDecision
    history_count: int


class VideoFrameSample(BaseModel):
    """One sampled video frame and the monitoring decision it produced."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str
    frame_index: int
    source_timestamp_seconds: float | None = None
    monitoring_result: dict[str, Any]


class VideoMonitoringSession(BaseModel):
    """Outcome of a bounded or explicitly stopped video-monitoring session."""

    animal_id: str
    animal_name: str | None = None
    expected_species: str | None = None
    source: str
    samples: list[VideoFrameSample] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    ended_reason: str
