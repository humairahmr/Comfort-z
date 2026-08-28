"""Schemas shared by Gemini, storage, and alert logic."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field

class Severity(str, Enum):
    NORMAL = "normal"
    MONITOR = "monitor"
    CONCERNING = "potentially_concerning"

class Trend(str, Enum):
    FIRST_OBSERVATION = "first_observation"
    UNCHANGED = "unchanged"
    IMPROVING = "improving"
    WORSENING = "worsening"
    PERSISTING = "suspicious_pattern_persisting"

class GeminiObservation(BaseModel):
    species: str | None = Field(default=None, description="Species only if reasonably identifiable.")
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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    gemini_observation: GeminiObservation
    severity: Severity
    explanation: str

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
