"""Bounded, non-diagnostic external-research coordination for monitoring results.

Research stays optional: Google Search grounding is only invoked after the existing
conditional decision rules request it, and tests use small fakes rather than the network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Protocol
from urllib.parse import urlparse

from dotenv import load_dotenv
from google import genai
from google.genai import types

from comfort_z.models import (
    ResearchContext,
    ResearchDecision,
    ResearchResult,
    ResearchSource,
    ResearchSourceCategory,
    Severity,
    StoredObservation,
    Trend,
    OwnerUpdate,
)
from comfort_z.services.comparison import is_valid_animal_observation

MAX_RESEARCH_SOURCES = 5
RESEARCH_COOLDOWN = timedelta(hours=24)
MAX_GROUNDED_RESPONSE_CHARS = 500

load_dotenv()


class ResearchProvider(Protocol):
    """A future bounded web, specialist, or community evidence retriever."""

    def search(self, query: str, *, max_sources: int) -> list[ResearchSource]:
        """Return short source summaries only; callers must not persist raw pages."""


class ResearchProviderError(RuntimeError):
    """A safe, non-secret-bearing research retrieval error."""


class GoogleSearchResearchProvider:
    """Text-only Gemini Google Search grounding provider for conditional research."""

    def __init__(self, *, model: str | None = None, api_key: str | None = None, client=None) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        # Google API key is the documented Cloud Run secret; preserve GEMINI_API_KEY
        # as the project-wide fallback for local development.
        self.api_key = api_key if api_key is not None else (
            os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        )
        self.client = client

    def search(self, query: str, *, max_sources: int) -> list[ResearchSource]:
        if not self.api_key:
            raise ResearchProviderError(
                "Google Search research requires GOOGLE_API_KEY or GEMINI_API_KEY."
            )
        if not query.strip():
            raise ResearchProviderError("Google Search research requires a non-empty question.")
        client = self.client or genai.Client(api_key=self.api_key)
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=_grounded_research_prompt(query),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=600,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
        except Exception as error:
            raise _safe_provider_error(error) from error

        answer = _compact_text(_read(response, "text"))
        if not answer:
            raise ResearchProviderError("Google Search research returned no usable grounded response.")
        sources = _grounding_sources(response, answer, max_sources=max(1, min(max_sources, MAX_RESEARCH_SOURCES)))
        if not sources:
            raise ResearchProviderError("Google Search research returned no usable citations.")
        return sources


def get_research_provider() -> ResearchProvider | None:
    """Select an opt-in provider; local/test runs remain network-free by default."""
    if os.getenv("RESEARCH_PROVIDER", "").strip().lower() == "google_search":
        return GoogleSearchResearchProvider()
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

    question = _research_question(current, trend)
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
    owner_updates: list[OwnerUpdate] | None = None,
    now: datetime | None = None,
) -> ResearchContext:
    """Run at most one small provider query, preserving monitoring on every failure."""
    decision = decide_research(current, prior, trend=trend, alert_status=alert_status)
    if not decision.needed:
        return ResearchContext(decision=decision)

    bounded_owner_updates = list(owner_updates or [])[:8]
    if bounded_owner_updates:
        decision = decision.model_copy(
            update={
                "research_question": _research_question(
                    current, trend, owner_updates=bounded_owner_updates
                )
            }
        )
    owner_update_ids = [update.owner_update_id for update in bounded_owner_updates]

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
            owner_update_ids=owner_update_ids,
        )
    if provider is None:
        return ResearchContext(
            decision=decision,
            failure="Research was considered, but no research provider is configured. Monitoring continued unchanged.",
            owner_update_ids=owner_update_ids,
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
        return ResearchContext(
            decision=decision,
            result=result,
            owner_update_ids=owner_update_ids,
        )
    except Exception:
        # Do not leak provider internals, URLs with tokens, or credentials to an API result.
        return ResearchContext(
            decision=decision,
            failure="Research retrieval was unavailable. Monitoring and the existing alert decision continued unchanged.",
            owner_update_ids=owner_update_ids,
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


def _research_question(
    current: StoredObservation,
    trend: Trend,
    *,
    owner_updates: list[OwnerUpdate] | None = None,
) -> str:
    animal = current.expected_species or current.animal_name or current.animal_id
    visual = current.gemini_observation
    observed = "; ".join(
        part
        for part in (
            f"posture: {visual.posture}",
            f"activity: {visual.activity_level}",
            f"movement: {visual.apparent_movement}",
            f"visible findings: {', '.join(visual.visible_abnormalities)}" if visual.visible_abnormalities else None,
        )
        if part
    )
    environment = _research_environment_context(current)
    question = (
        f"What non-diagnostic, authoritative animal-care guidance is relevant for {animal} with "
        f"a {current.severity.value} observed behavior pattern and a {trend.value} trend? "
        f"Observed context: {observed}. {environment}"
    )
    owner_context = _owner_reported_research_context(owner_updates or [])
    return f"{question} {owner_context}" if owner_context else question


def _owner_reported_research_context(owner_updates: list[OwnerUpdate]) -> str:
    """Keep owner context distinct and small when research already has a visual trigger."""
    entries: list[str] = []
    for update in owner_updates[:8]:
        if update.reading is not None:
            detail = f"{update.reading.reading_type} {update.reading.value} {update.reading.unit}"
        else:
            detail = " ".join((update.note or "").split())[:160]
        if detail:
            entries.append(f"{update.category.value}: {detail}")
    if not entries:
        return ""
    return (
        "OWNER-REPORTED / UNVERIFIED CONTEXT (not visual evidence; do not present it as "
        "an observed finding): " + "; ".join(entries) + "."
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


def _grounded_research_prompt(question: str) -> str:
    return (
        "Comfort-z is an animal-monitoring system asking a bounded follow-up question. "
        "Use Google Search grounding only as needed to find reliable veterinary, institutional, "
        "animal-welfare, specialist, or manufacturer documentation evidence first. Do not diagnose "
        "the animal or claim that web evidence proves a condition. Clearly separate established guidance "
        "from community/forum anecdotes, mention conflicts or uncertainty, and do not provide medication, "
        "chemical, dosing, invasive-treatment, or emergency-procedure instructions. If serious risk is "
        "plausible, state that an appropriate veterinarian or animal-care professional should be contacted. "
        "Return a concise evidence-focused answer suitable for provenance; cite sources through grounding.\n\n"
        f"Research question: {question}"
    )


def _grounding_sources(response, answer: str, *, max_sources: int) -> list[ResearchSource]:
    candidates = _read(response, "candidates") or []
    candidate = candidates[0] if candidates else None
    metadata = _read(candidate, "grounding_metadata") if candidate is not None else None
    chunks = _read(metadata, "grounding_chunks") or []
    evidence_by_chunk = _grounding_evidence(metadata)
    sources: list[ResearchSource] = []
    seen_references: set[str] = set()
    for index, chunk in enumerate(chunks):
        web = _read(chunk, "web")
        reference = _read(web, "uri")
        title = _read(web, "title")
        if not reference or not title or reference in seen_references:
            continue
        seen_references.add(reference)
        sources.append(
            ResearchSource(
                title=title,
                reference=reference,
                source_name=_read(web, "domain"),
                category=categorize_source(reference, title=title),
                evidence=_compact_text(evidence_by_chunk.get(index) or answer),
            )
        )
        if len(sources) >= max_sources:
            return sources

    # Some supported SDK responses expose legacy citation metadata instead of
    # grounding chunks. Keep this narrow and never fabricate a title or URL.
    citations = _read(_read(candidate, "citation_metadata"), "citations") or []
    for citation in citations:
        reference = _read(citation, "uri")
        title = _read(citation, "title")
        if not reference or not title or reference in seen_references:
            continue
        seen_references.add(reference)
        sources.append(
            ResearchSource(
                title=title,
                reference=reference,
                category=categorize_source(reference, title=title),
                evidence=_compact_text(answer),
            )
        )
        if len(sources) >= max_sources:
            break
    return sources


def categorize_source(reference: str, *, title: str | None = None) -> ResearchSourceCategory:
    """Classify only clear signals; uncertain web pages remain unknown."""
    host = (urlparse(reference).hostname or "").lower().removeprefix("www.")
    label = (title or "").lower()
    if host == "reddit.com" or host.endswith(".reddit.com") or any(
        marker in host for marker in ("forum", "forums", "community", "discussion", "discourse", "board")
    ):
        return ResearchSourceCategory.COMMUNITY
    if (
        host.endswith(".gov")
        or ".gov." in host
        or host.endswith(".edu")
        or ".edu." in host
        or ".ac." in host
        or any(marker in host for marker in ("veterinary", "vet-", "vet.", "animalwelfare", "humane"))
    ):
        return ResearchSourceCategory.AUTHORITATIVE
    if (
        host.startswith(("docs.", "support.", "manual."))
        and any(marker in label for marker in ("documentation", "manual", "product", "support"))
    ):
        return ResearchSourceCategory.MANUFACTURER_DOCUMENTATION
    return ResearchSourceCategory.UNKNOWN


def _grounding_evidence(metadata) -> dict[int, str]:
    evidence: dict[int, list[str]] = {}
    for support in _read(metadata, "grounding_supports") or []:
        text = _read(_read(support, "segment"), "text")
        if not text:
            continue
        for index in _read(support, "grounding_chunk_indices") or []:
            evidence.setdefault(index, []).append(text)
    return {index: " ".join(parts) for index, parts in evidence.items()}


def _research_environment_context(current: StoredObservation) -> str:
    details: list[str] = []
    if current.environment_context:
        context = current.environment_context
        outdoor = []
        if context.outdoor_temperature_c is not None:
            outdoor.append(f"outdoor temperature {context.outdoor_temperature_c} C")
        if context.outdoor_humidity_percent is not None:
            outdoor.append(f"outdoor humidity {context.outdoor_humidity_percent}%")
        if context.weather_condition:
            outdoor.append(f"weather {context.weather_condition}")
        if outdoor:
            details.append("Outdoor context only (not enclosure conditions): " + ", ".join(outdoor) + ".")
    if current.direct_environment_readings:
        readings = ", ".join(
            f"{reading.reading_type} {reading.value} {reading.unit} (owner-provided)"
            for reading in current.direct_environment_readings
        )
        details.append("Direct enclosure readings: " + readings + ".")
    if current.missing_direct_reading_requests:
        details.append("Missing direct-reading request: " + " ".join(current.missing_direct_reading_requests))
    return " ".join(details) or "No environment readings were supplied."


def _safe_provider_error(error: Exception) -> ResearchProviderError:
    message = str(error).lower()
    if "429" in message or "resource_exhausted" in message or "quota" in message:
        return ResearchProviderError("Google Search research quota is currently exhausted.")
    if "503" in message or "unavailable" in message or "temporar" in message:
        return ResearchProviderError("Google Search research is temporarily unavailable.")
    if "unsupported" in message or "not supported" in message or "invalid_argument" in message:
        return ResearchProviderError("Google Search grounding is not supported by the configured Gemini model.")
    return ResearchProviderError("Google Search research could not be completed.")


def _read(value, name: str):
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name) or value.get(_camel_case(name))
    return getattr(value, name, None)


def _camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _compact_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_GROUNDED_RESPONSE_CHARS]
