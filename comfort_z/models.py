"""Schemas shared by Gemini, storage, and alert logic."""
from __future__ import annotations
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator

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


class MonitoringSourceType(str, Enum):
    VIDEO = "video"
    WEBCAM = "webcam"


class SamplingMode(str, Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"


class ResearchSourceCategory(str, Enum):
    """Quality classification for compact, persisted external research evidence."""

    AUTHORITATIVE = "authoritative"
    MANUFACTURER_DOCUMENTATION = "manufacturer_documentation"
    COMMUNITY = "community"
    UNKNOWN = "unknown"


class ResearchDecision(BaseModel):
    """Why bounded external research was, or was not, considered useful."""

    needed: bool
    reason: str
    research_question: str | None = None
    trigger_type: str | None = None
    confidence: float = Field(ge=0, le=1)


class ResearchSource(BaseModel):
    """A short provenance record; never store a retrieved source's raw page body."""

    title: str
    reference: str
    category: ResearchSourceCategory
    evidence: str
    source_name: str | None = None
    # A provider may label an explicitly contradictory source without asking the
    # monitoring model to infer agreement from unstructured text.
    stance: Literal["supports", "conflicts", "unknown"] = "unknown"


class ResearchResult(BaseModel):
    query: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sources: list[ResearchSource] = Field(default_factory=list)
    evidence_summary: str
    community_summary: str
    conflicts_or_uncertainty: str
    recommendation: str
    confidence: float = Field(ge=0, le=1)


class ResearchContext(BaseModel):
    """Conditional research attached to one observation and reusable by reports."""

    decision: ResearchDecision
    result: ResearchResult | None = None
    failure: str | None = None
    reused_from_observation_id: str | None = None


class DirectEnvironmentReading(BaseModel):
    """An owner-supplied measurement, distinct from outdoor weather context."""

    reading_type: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["owner"] = "owner"


class OwnerUpdateCategory(str, Enum):
    """The kind of owner-provided context recorded outside visual observations."""

    MEASUREMENT = "measurement"
    FEEDING = "feeding"
    CARE = "care"
    APPETITE = "appetite"
    BEHAVIOR = "behavior"
    AVAILABILITY = "availability"
    NOTE = "note"


class OwnerUpdate(BaseModel):
    """Persistent owner context; it is never a Gemini visual observation."""

    owner_update_id: str = Field(default_factory=lambda: str(uuid4()))
    animal_id: str = Field(min_length=1)
    category: OwnerUpdateCategory
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["owner"] = "owner"
    # Voice ingestion can normalize into this same record later without changing history.
    input_method: Literal["typed", "voice"] = "typed"
    note: str | None = Field(default=None, max_length=500)
    reading: DirectEnvironmentReading | None = None

    @model_validator(mode="after")
    def validate_owner_update(self) -> "OwnerUpdate":
        if self.occurred_at.tzinfo is None or self.recorded_at.tzinfo is None:
            raise ValueError("owner update timestamps must include a timezone.")
        self.occurred_at = self.occurred_at.astimezone(timezone.utc)
        self.recorded_at = self.recorded_at.astimezone(timezone.utc)
        note = self.note.strip() if self.note else None
        if self.category == OwnerUpdateCategory.MEASUREMENT:
            if self.reading is None:
                raise ValueError("measurement updates require a direct reading.")
            self.reading = self.reading.model_copy(update={"recorded_at": self.occurred_at})
            if note == "":
                self.note = None
            return self
        if self.reading is not None:
            raise ValueError("only measurement updates may include a direct reading.")
        if not note:
            raise ValueError("non-measurement updates require a non-empty note.")
        self.note = note
        return self


class EnvironmentContext(BaseModel):
    """Outdoor/local conditions that may support, but never replace, enclosure data."""

    provider: str
    location_name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    context_type: Literal["observed", "forecast"] = "observed"
    outdoor_temperature_c: float | None = None
    outdoor_humidity_percent: float | None = Field(default=None, ge=0, le=100)
    weather_condition: str | None = None
    observed_at: datetime
    context_note: str = (
        "Outdoor/local weather context only; it is not a direct enclosure, room, water, "
        "terrarium, or cage reading."
    )

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
    environment_context: EnvironmentContext | None = None
    direct_environment_readings: list[DirectEnvironmentReading] = Field(default_factory=list)
    # Bounded provenance only; owner wording remains in the owner-updates repository.
    owner_update_ids: list[str] = Field(default_factory=list)
    missing_direct_reading_requests: list[str] = Field(default_factory=list)
    research_context: ResearchContext | None = None
    # Persist the existing policy outcome so period reports can describe alerts
    # without re-running comparison logic against historical records.
    alert_status: bool = False
    trend: Trend | None = None

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
    source_frame_index: int | None = None
    source_timestamp_seconds: float | None = None
    monitoring_result: dict[str, Any]


class VideoMonitoringSession(BaseModel):
    """Outcome of a bounded or explicitly stopped video-monitoring session."""

    animal_id: str
    animal_name: str | None = None
    expected_species: str | None = None
    source: str
    attempted_samples: int = 0
    samples: list[VideoFrameSample] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    ended_reason: str
    last_attempt_source_timestamp_seconds: float | None = None
    last_attempt_source_frame_index: int | None = None
    next_source_cursor_seconds: float | None = None


class MonitoringProfile(BaseModel):
    """Persisted, quota-conscious instructions for one animal source."""

    animal_id: str = Field(min_length=1)
    animal_name: str | None = None
    expected_species: str | None = None
    location_name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    enclosure_type: str | None = None
    direct_environment_readings: list[DirectEnvironmentReading] = Field(default_factory=list)
    monitoring_goal: str = Field(min_length=1)
    source_reference: str | int | None = None
    source_type: MonitoringSourceType | None = None
    normal_sampling_interval_seconds: float = Field(gt=0)
    elevated_sampling_interval_seconds: float = Field(gt=0)
    current_sampling_mode: SamplingMode = SamplingMode.NORMAL
    daily_sample_budget: int = Field(gt=0)
    samples_used_in_current_period: int = Field(default=0, ge=0)
    budget_period_date: date = Field(default_factory=lambda: datetime.now(timezone.utc).date())
    source_cursor_seconds: float = Field(default=0, ge=0)
    # The next prerecorded-video frame to read. None preserves legacy timestamp-only profiles.
    source_cursor_frame_index: int | None = Field(default=None, ge=0)
    active: bool = True
    report_time: str = "08:00"
    timezone: str = "UTC"
    last_monitoring_run: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_source_connection(self) -> "MonitoringProfile":
        """A source is either fully configured or intentionally absent."""
        if isinstance(self.source_reference, str) and not self.source_reference.strip():
            raise ValueError("source_reference cannot be empty when provided.")
        has_reference = self.source_reference is not None
        has_type = self.source_type is not None
        if has_reference != has_type:
            raise ValueError(
                "source_reference and source_type must be provided together or both omitted."
            )
        return self

    @property
    def has_monitoring_source(self) -> bool:
        """Derived source state; it is never persisted as mutable profile data."""
        return self.source_reference is not None and self.source_type is not None


class DailyReportNarrative(BaseModel):
    """Gemini's bounded text summary of already-structured observations."""

    overall_activity_behavior: str
    notable_changes: list[str] = Field(default_factory=list)
    concerning_observations: list[str] = Field(default_factory=list)
    visibility_data_quality_limitations: str
    comparison_with_prior_observations: str
    recommended_action: str
    owner_reported_context: list[str] = Field(default_factory=list)


class DailyMonitoringReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    animal_id: str
    animal_name: str | None = None
    expected_species: str | None = None
    period_start: datetime
    period_end: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_observation_count: int = Field(ge=0)
    animal_not_visible_count: int = Field(ge=0)
    uncertain_observation_count: int = Field(ge=0)
    concerning_observation_ids: list[str] = Field(default_factory=list)
    alert_observation_ids: list[str] = Field(default_factory=list)
    owner_update_ids: list[str] = Field(default_factory=list)
    narrative: DailyReportNarrative


class MonitoringWindowResult(BaseModel):
    """One finite monitoring invocation; never a permanently running camera loop."""

    animal_id: str
    active: bool
    sampling_mode: SamplingMode
    source_cursor_seconds: float = Field(ge=0)
    source_cursor_frame_index: int | None = Field(default=None, ge=0)
    samples_used_in_current_period: int = Field(ge=0)
    remaining_daily_sample_budget: int = Field(ge=0)
    ended_reason: str
    session: VideoMonitoringSession | None = None
