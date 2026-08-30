from datetime import datetime, timedelta, timezone

from comfort_z.models import (
    DailyReportNarrative,
    DirectEnvironmentReading,
    EnvironmentContext,
    GeminiObservation,
    MonitoringProfile,
    MonitoringSourceType,
    ObservationStatus,
    OwnerUpdate,
    OwnerUpdateCategory,
    ResearchContext,
    ResearchDecision,
    ResearchResult,
    ResearchSource,
    ResearchSourceCategory,
    Severity,
    StoredObservation,
    Trend,
)
from comfort_z.services.orchestration import generate_daily_report
from comfort_z.services.research import decide_research, evaluate_research, maybe_research
from comfort_z.services.repository import (
    LocalJsonMonitoringStateRepository,
    LocalJsonObservationRepository,
)
from comfort_z.tools import monitoring


def make_observation(
    *,
    severity=Severity.MONITOR,
    status=ObservationStatus.VALID,
    timestamp=None,
    uncertainty="One frame only.",
):
    visual = GeminiObservation(
        animal_visible=status == ObservationStatus.VALID,
        observation_status=status,
        posture="resting" if status == ObservationStatus.VALID else "unclear",
        activity_level="low" if status == ObservationStatus.VALID else "unclear",
        apparent_movement="still" if status == ObservationStatus.VALID else "not assessable",
        visible_abnormalities=["unusual posture"] if severity != Severity.NORMAL else [],
        confidence=0.8,
        behavioral_interpretation="Structured test observation.",
        uncertainty=uncertainty,
        severity=severity,
    )
    return StoredObservation(
        animal_id="raku",
        animal_name="Raku",
        expected_species="Test animal",
        timestamp=timestamp or datetime.now(timezone.utc),
        gemini_observation=visual,
        severity=severity,
        explanation=visual.behavioral_interpretation,
    )


def test_research_decision_excludes_normal_invisible_and_first_mild_observations():
    normal = make_observation(severity=Severity.NORMAL)
    hidden = make_observation(status=ObservationStatus.ANIMAL_NOT_VISIBLE)
    mild = make_observation(severity=Severity.MONITOR)

    assert not decide_research(normal, [], trend=Trend.FIRST_OBSERVATION, alert_status=False).needed
    assert not decide_research(hidden, [], trend=Trend.INSUFFICIENT_VISIBILITY, alert_status=False).needed
    assert not decide_research(mild, [], trend=Trend.FIRST_OBSERVATION, alert_status=False).needed


def test_research_decision_triggers_for_repeated_worsening_and_alert_patterns():
    mild_prior = make_observation(severity=Severity.MONITOR)
    worsening = make_observation(severity=Severity.CONCERNING)

    repeated = decide_research(mild_prior, [mild_prior], trend=Trend.PERSISTING, alert_status=False)
    worsening_decision = decide_research(worsening, [mild_prior], trend=Trend.WORSENING, alert_status=False)
    alert_decision = decide_research(worsening, [], trend=Trend.FIRST_OBSERVATION, alert_status=True)

    assert repeated.needed and repeated.trigger_type == "persistent_abnormality"
    assert worsening_decision.needed and worsening_decision.trigger_type == "worsening"
    assert alert_decision.needed and alert_decision.trigger_type == "alert"


def test_research_decision_can_record_unresolved_uncertainty_for_a_recurring_pattern():
    prior = make_observation(severity=Severity.MONITOR)
    current = make_observation(
        severity=Severity.MONITOR,
        uncertainty="The visible posture is unclear; further assessment is needed.",
    )

    decision = decide_research(current, [prior], trend=Trend.UNCHANGED, alert_status=False)

    assert decision.needed
    assert decision.trigger_type == "unresolved_uncertainty"


def test_research_question_carries_observation_trend_and_environment_context():
    current = make_observation(severity=Severity.CONCERNING).model_copy(
        update={
            "environment_context": EnvironmentContext(
                provider="test",
                outdoor_temperature_c=31,
                observed_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
            ),
            "direct_environment_readings": [
                DirectEnvironmentReading(reading_type="water_temperature", value=25, unit="C")
            ],
        }
    )

    decision = decide_research(current, [], trend=Trend.WORSENING, alert_status=False)

    assert "worsening" in decision.research_question
    assert "posture: resting" in decision.research_question
    assert "Outdoor context only" in decision.research_question
    assert "water_temperature 25.0 C" in decision.research_question


def test_research_evaluation_prefers_authoritative_evidence_and_labels_disagreement():
    current = make_observation(severity=Severity.CONCERNING)
    sources = [
        ResearchSource(
            title="Veterinary guidance",
            reference="https://example.test/vet",
            source_name="Veterinary Hospital",
            category=ResearchSourceCategory.AUTHORITATIVE,
            evidence="Arrange professional assessment when concerning signs persist.",
        ),
        ResearchSource(
            title="Forum thread",
            reference="https://example.test/forum",
            source_name="Animal forum",
            category=ResearchSourceCategory.COMMUNITY,
            evidence="Several owners describe trying a home remedy.",
            stance="conflicts",
        ),
    ]

    result = evaluate_research(
        query="test query",
        sources=sources,
        current=current,
        alert_status=True,
        retrieved_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )

    assert "Veterinary Hospital" in result.evidence_summary
    assert "anecdotal" in result.community_summary
    assert "disagree" in result.conflicts_or_uncertainty
    assert "Do not start medication" in result.recommendation
    assert result.confidence == 0.8


class MemoryRepository:
    def __init__(self):
        self.saved = []

    def recent_for_animal(self, _animal_id, limit=5):
        return self.saved[-limit:][::-1]

    def save(self, observation):
        self.saved.append(observation)
        return observation


class SequencedAnalyzer:
    def __init__(self, observations):
        self.observations = iter(observations)

    def analyze_file(self, *_args, **_kwargs):
        return next(self.observations)


class FakeResearchProvider:
    def __init__(self, *, error=False):
        self.calls = []
        self.error = error

    def search(self, query, *, max_sources):
        self.calls.append((query, max_sources))
        if self.error:
            raise RuntimeError("provider unavailable")
        return [
            ResearchSource(
                title="Specialist guidance",
                reference="https://example.test/specialist",
                category=ResearchSourceCategory.AUTHORITATIVE,
                evidence="Continue clear observation and obtain professional advice if signs persist.",
            )
        ]


def test_research_uses_bounded_owner_context_only_after_visual_trigger():
    provider = FakeResearchProvider()
    owner_updates = [
        OwnerUpdate(
            animal_id="raku",
            category=OwnerUpdateCategory.APPETITE,
            note=f"Owner-reported appetite note {index}.",
            occurred_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        )
        for index in range(10)
    ]
    normal = make_observation(severity=Severity.NORMAL)

    not_needed = maybe_research(
        normal,
        [],
        trend=Trend.FIRST_OBSERVATION,
        alert_status=False,
        provider=provider,
        owner_updates=owner_updates,
    )
    needed = maybe_research(
        make_observation(severity=Severity.CONCERNING),
        [],
        trend=Trend.WORSENING,
        alert_status=False,
        provider=provider,
        owner_updates=owner_updates,
    )

    assert not not_needed.decision.needed
    assert not_needed.owner_update_ids == []
    assert len(provider.calls) == 1
    query, max_sources = provider.calls[0]
    assert max_sources == 5
    assert "OWNER-REPORTED / UNVERIFIED CONTEXT" in query
    assert "not visual evidence" in query
    assert len(needed.owner_update_ids) == 8


def visual(severity):
    return make_observation(severity=severity).gemini_observation


def test_monitoring_persists_research_provenance_and_reuses_matching_result(monkeypatch):
    repository = MemoryRepository()
    analyzer = SequencedAnalyzer([visual(Severity.MONITOR), visual(Severity.MONITOR), visual(Severity.MONITOR)])
    provider = FakeResearchProvider()
    monkeypatch.setattr(monitoring, "get_repository", lambda: repository)
    monkeypatch.setattr(monitoring, "GeminiVisualAnalyzer", lambda: analyzer)
    monkeypatch.setattr(monitoring, "get_research_provider", lambda: provider)

    first = monitoring.monitor_animal("raku", "unused.jpg")
    second = monitoring.monitor_animal("raku", "unused.jpg")
    third = monitoring.monitor_animal("raku", "unused.jpg")

    assert first["observation"]["research_context"]["decision"]["needed"] is False
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == 5
    assert second["observation"]["research_context"]["result"]["sources"][0]["category"] == "authoritative"
    assert third["observation"]["research_context"]["reused_from_observation_id"] == repository.saved[1].observation_id


def test_provider_failure_never_changes_monitoring_alert_or_prevents_persistence(monkeypatch):
    repository = MemoryRepository()
    prior = make_observation(severity=Severity.NORMAL)
    repository.save(prior)
    analyzer = SequencedAnalyzer([visual(Severity.CONCERNING)])
    provider = FakeResearchProvider(error=True)
    monkeypatch.setattr(monitoring, "get_repository", lambda: repository)
    monkeypatch.setattr(monitoring, "GeminiVisualAnalyzer", lambda: analyzer)
    monkeypatch.setattr(monitoring, "get_research_provider", lambda: provider)

    result = monitoring.monitor_animal("raku", "unused.jpg")

    assert result["decision"]["alert_status"] is True
    assert result["observation"]["alert_status"] is True
    assert "unavailable" in result["observation"]["research_context"]["failure"]
    assert len(repository.saved) == 2


def test_structured_research_provenance_survives_local_repository_round_trip(tmp_path):
    result = ResearchResult(
        query="saved query",
        sources=[
            ResearchSource(
                title="Specialist guidance",
                reference="https://example.test/specialist",
                category=ResearchSourceCategory.AUTHORITATIVE,
                evidence="Short source evidence.",
            )
        ],
        evidence_summary="Short authoritative summary.",
        community_summary="No community anecdotes were used.",
        conflicts_or_uncertainty="Remaining uncertainty.",
        recommendation="Continue cautious monitoring.",
        confidence=0.8,
    )
    observation = make_observation().model_copy(
        update={
            "research_context": ResearchContext(
                decision=ResearchDecision(
                    needed=True,
                    reason="Recurring concern.",
                    research_question="saved query",
                    trigger_type="persistent_abnormality",
                    confidence=0.8,
                ),
                result=result,
            )
        }
    )
    repository = LocalJsonObservationRepository(tmp_path / "observations.json")

    repository.save(observation)
    loaded = repository.recent_for_animal("raku")[0]

    assert loaded.research_context is not None
    assert loaded.research_context.result.sources[0].category == ResearchSourceCategory.AUTHORITATIVE


class CapturingReportGenerator:
    def __init__(self):
        self.payload = None

    def generate(self, structured_history):
        self.payload = structured_history
        return DailyReportNarrative(
            overall_activity_behavior="Structured report.",
            visibility_data_quality_limitations="None.",
            comparison_with_prior_observations="Compared.",
            recommended_action="Continue monitoring.",
        )


class HistoryRepository:
    def __init__(self, observations):
        self.observations = observations

    def history_for_animal(self, animal_id):
        return [item for item in self.observations if item.animal_id == animal_id]


def test_daily_report_uses_saved_research_context_without_provider_call(tmp_path):
    saved_result = ResearchResult(
        query="saved query",
        sources=[],
        evidence_summary="Saved authoritative summary.",
        community_summary="No community anecdotes were used.",
        conflicts_or_uncertainty="Saved uncertainty.",
        recommendation="Saved recommendation.",
        confidence=0.8,
    )
    observation = make_observation(
        severity=Severity.CONCERNING,
        timestamp=datetime(2026, 8, 28, 10, tzinfo=timezone.utc),
    ).model_copy(
        update={
            "research_context": ResearchContext(
                decision=ResearchDecision(
                    needed=True,
                    reason="Repeated concern.",
                    research_question="saved query",
                    trigger_type="persistent_abnormality",
                    confidence=0.8,
                ),
                result=saved_result,
            )
        }
    )
    state = LocalJsonMonitoringStateRepository(tmp_path / "state.json")
    state.save_profile(
        MonitoringProfile(
            animal_id="raku",
            monitoring_goal="Keep an eye on Raku.",
            source_reference="Raku.mp4",
            source_type=MonitoringSourceType.VIDEO,
            normal_sampling_interval_seconds=5,
            elevated_sampling_interval_seconds=1,
            daily_sample_budget=5,
        )
    )
    generator = CapturingReportGenerator()

    generate_daily_report(
        "raku",
        state_repository=state,
        observation_repository=HistoryRepository([observation]),
        report_generator=generator,
        now=datetime(2026, 8, 29, 8, 5, tzinfo=timezone.utc),
    )

    context = generator.payload["valid_observations"][0]["research_context"]
    assert context["result"]["query"] == "saved query"
