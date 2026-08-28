"""Bounded, non-diagnostic external-research coordination for monitoring results.

This module deliberately contains no network provider.  A future provider can implement
``ResearchProvider`` while tests use small fakes.  That keeps research optional and
prevents ordinary monitoring from silently starting web traffic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from comfort_z.models import (
    ResearchContext,
    ResearchDecision,
    ResearchResult,
    ResearchSource,
    ResearchSourceCategory,
    Severity,
    StoredObservation,
    Trend,
)
from comfort_z.services.comparison import is_valid_animal_observation

MAX_RESEARCH_SOURCES = 5
RESEARCH_COOLDOWN = timedelta(hours=24)


class ResearchProvider(Protocol):
    """A future bounded web, specialist, or community evidence retriever."""

    def search(self, query: str, *, max_sources: int) -> list[ResearchSource]:
        """Return short source summaries only; callers must not persist raw pages."""


def get_research_provider() -> ResearchProvider | None:
    """Return the configured provider when one is intentionally added in the future.

    No provider is configured in this change: research decisions and provenance remain
    usable without introducing real network calls or credentials.
    """
    return None


def decide_research(
    current: StoredObservation,
    prior: list[StoredObservation],
    *,
    trend: Trend,
    alert_status: bool,
) -> ResearchDecision:
    """Choose whether bounded evidence retrieval could materially help this pattern."""
    if not is_valid_animal_observation(current):
        return ResearchDecision(
            needed=False,
            reason="Research is not useful until the expected animal is sufficiently visible.",
            confidence=0.95,
        )
    if current.severity == Severity.NORMAL:
        return ResearchDecision(
            needed=False,
            reason="A normal valid observation does not justify external research.",
            confidence=0.95,
        )

    question = _research_question(current)
    valid_prior = [item for item in prior if is_valid_animal_observation(item)]
    abnormal_prior = [item for item in valid_prior if item.severity != Severity.NORMAL]
    uncertainty = (current.gemini_observation.uncertainty or "").lower()

    if alert_status:
        return _needed(question, "alert", "The existing monitoring alert is active, so bounded evidence may help frame a cautious next step.", 0.95)
    if trend == Trend.WORSENING:
        return _needed(question, "worsening", "A valid observation is worsening relative to saved history.", 0.9)
    if _actionable_uncertainty(uncertainty) and abnormal_prior:
        return _needed(question, "unresolved_uncertainty", "Gemini recorded unresolved uncertainty alongside a recurring non-normal pattern.", 0.7)
    if trend == Trend.PERSISTING or abnormal_prior:
        return _needed(question, "persistent_abnormality", "A non-normal valid observation is recurring across saved history.", 0.85)
    if current.severity == Severity.CONCERNING:
        return _needed(question, "concerning_observation", "A clear potentially concerning observation may warrant bounded supporting evidence.", 0.8)
    return ResearchDecision(
        needed=False,
        reason="A first isolated mild observation should be monitored before external research is requested.",
        confidence=0.8,
    )


def maybe_research(
    current: StoredObservation,
    prior: list[StoredObservation],
    *,
    trend: Trend,
    alert_status: bool,
    provider: ResearchProvider | None,
    now: datetime | None = None,
) -> ResearchContext:
    """Run at most one small provider query, preserving monitoring on every failure."""
    decision = decide_research(current, prior, trend=trend, alert_status=alert_status)
    if not decision.needed:
        return ResearchContext(decision=decision)

    timestamp = now or datetime.now(timezone.utc)
    cached = _recent_matching_research(prior, decision.research_question, timestamp)
    if cached is not None:
        return ResearchContext(
            decision=ResearchDecision(
                needed=False,
                reason="A matching research result is still within the cooldown window; the saved result was reused.",
                research_question=decision.research_question,
                trigger_type="cooldown_reused",
                confidence=0.95,
            ),
            result=cached.research_context.result,
            reused_from_observation_id=cached.observation_id,
        )
    if provider is None:
        return ResearchContext(
            decision=decision,
            failure="Research was considered, but no research provider is configured. Monitoring continued unchanged.",
        )
    try:
        sources = provider.search(decision.research_question or "", max_sources=MAX_RESEARCH_SOURCES)
        result = evaluate_research(
            query=decision.research_question or "",
            sources=sources[:MAX_RESEARCH_SOURCES],
            current=current,
            alert_status=alert_status,
            retrieved_at=timestamp,
        )
        return ResearchContext(decision=decision, result=result)
    except Exception:
        # Do not leak provider internals, URLs with tokens, or credentials to an API result.
        return ResearchContext(
            decision=decision,
            failure="Research retrieval was unavailable. Monitoring and the existing alert decision continued unchanged.",
        )


def evaluate_research(
    *,
    query: str,
    sources: list[ResearchSource],
    current: StoredObservation,
    alert_status: bool,
    retrieved_at: datetime,
) -> ResearchResult:
    """Prefer authoritative evidence and explicitly bound community anecdotes."""
    authoritative = [
        source
        for source in sources
        if source.category
        in {ResearchSourceCategory.AUTHORITATIVE, ResearchSourceCategory.MANUFACTURER_DOCUMENTATION}
    ]
    community = [source for source in sources if source.category == ResearchSourceCategory.COMMUNITY]
    authoritative_summary = _source_summary(authoritative)
    community_summary = _source_summary(community)
    if not authoritative_summary:
        authoritative_summary = "No authoritative or manufacturer/documentation source was returned."
    if community_summary:
        community_summary = f"Community reports (anecdotal, not independently verified): {community_summary}"
    else:
        community_summary = "No community anecdotes were used."

    disagreement = any(source.stance == "conflicts" for source in community)
    if authoritative and community and disagreement:
        conflicts = (
            "Authoritative guidance and community anecdotes disagree. Community reports are "
            "anecdotal and do not override authoritative or professional guidance."
        )
    elif authoritative and community:
        conflicts = (
            "Community reports are included as anecdotal context only and are not independently "
            "verified or treated as a substitute for authoritative guidance."
        )
    elif not sources:
        conflicts = "The provider returned no usable sources, so no external conclusion was drawn."
    else:
        conflicts = "External evidence remains limited; the observation and monitoring history remain primary context."

    recommendation = _recommendation(current, alert_status)
    confidence = 0.8 if authoritative else (0.35 if community else 0.1)
    return ResearchResult(
        query=query,
        retrieved_at=retrieved_at,
        sources=sources,
        evidence_summary=authoritative_summary,
        community_summary=community_summary,
        conflicts_or_uncertainty=conflicts,
        recommendation=recommendation,
        confidence=confidence,
    )


def _needed(question: str, trigger: str, reason: str, confidence: float) -> ResearchDecision:
    return ResearchDecision(
        needed=True,
        reason=reason,
        research_question=question,
        trigger_type=trigger,
        confidence=confidence,
    )


def _research_question(current: StoredObservation) -> str:
    animal = current.expected_species or current.animal_name or current.animal_id
    return (
        f"What non-diagnostic, authoritative animal-care guidance is relevant when {animal} "
        f"has a {current.severity.value} observed behavior pattern?"
    )


def _actionable_uncertainty(text: str) -> bool:
    return any(marker in text for marker in ("unable", "cannot", "unclear", "not enough", "further assessment"))


def _recent_matching_research(
    prior: list[StoredObservation], query: str | None, now: datetime
) -> StoredObservation | None:
    if not query:
        return None
    for observation in prior:
        context = observation.research_context
        if context is None or context.result is None or context.result.query != query:
            continue
        if now - observation.timestamp <= RESEARCH_COOLDOWN:
            return observation
    return None


def _source_summary(sources: list[ResearchSource]) -> str:
    return " ".join(f"{source.source_name or source.title}: {source.evidence}" for source in sources)


def _recommendation(current: StoredObservation, alert_status: bool) -> str:
    if alert_status:
        return (
            "The existing alert remains in effect. Contact an appropriate veterinarian or animal-care "
            "professional, especially if the visible signs continue or worsen. Do not start medication, "
            "chemicals, dosing, invasive treatment, or emergency procedures from this research alone."
        )
    detail = " ".join(current.missing_direct_reading_requests)
    base = (
        "Use the saved observation history and authoritative guidance for cautious follow-up; continue "
        "clear monitoring and seek an appropriate veterinarian or animal-care professional if signs persist "
        "or worsen. Do not start medication, chemicals, dosing, invasive treatment, or emergency procedures "
        "from this research alone."
    )
    return f"{base} {detail}".strip()
