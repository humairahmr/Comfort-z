from types import SimpleNamespace

import pytest

from comfort_z.models import ResearchSourceCategory
from comfort_z.services import research
from comfort_z.services.research import GoogleSearchResearchProvider, ResearchProviderError


def grounded_response(*, text="Grounded response.", chunks=None, supports=None):
    metadata = SimpleNamespace(
        grounding_chunks=chunks or [],
        grounding_supports=supports or [],
    )
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(grounding_metadata=metadata, citation_metadata=None)],
    )


def web_chunk(title, uri, domain=None):
    return SimpleNamespace(web=SimpleNamespace(title=title, uri=uri, domain=domain))


class CapturingModels:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response=None, error=None):
        self.models = CapturingModels(response=response, error=error)


def test_google_search_provider_uses_grounding_tool_and_parses_cited_sources():
    support = SimpleNamespace(
        grounding_chunk_indices=[0],
        segment=SimpleNamespace(text="Professional guidance recommends documenting persistent changes."),
    )
    client = FakeClient(
        response=grounded_response(
            text="A concise grounded answer.",
            chunks=[web_chunk("Veterinary school guidance", "https://vet.example.edu/advice", "vet.example.edu")],
            supports=[support],
        )
    )
    provider = GoogleSearchResearchProvider(api_key="test-key", client=client)

    sources = provider.search("A precise animal-care question", max_sources=5)

    assert len(client.models.calls) == 1
    call = client.models.calls[0]
    assert call["model"] == "gemini-3.5-flash"
    assert call["config"].tools[0].google_search is not None
    assert "A precise animal-care question" in call["contents"]
    assert sources[0].title == "Veterinary school guidance"
    assert sources[0].evidence.startswith("Professional guidance")
    assert sources[0].category == ResearchSourceCategory.AUTHORITATIVE


def test_google_search_provider_limits_persisted_sources_to_requested_bound():
    client = FakeClient(
        response=grounded_response(
            chunks=[web_chunk(f"Source {index}", f"https://example{index}.test/page") for index in range(7)]
        )
    )
    provider = GoogleSearchResearchProvider(api_key="test-key", client=client)

    sources = provider.search("question", max_sources=5)

    assert len(sources) == 5


def test_google_search_source_categorization_is_conservative():
    assert research.categorize_source("https://animals.gov/guidance") == ResearchSourceCategory.AUTHORITATIVE
    assert research.categorize_source("https://www.reddit.com/r/aquariums/comments/1") == ResearchSourceCategory.COMMUNITY
    assert research.categorize_source("https://example.test/article") == ResearchSourceCategory.UNKNOWN
    assert research.categorize_source(
        "https://docs.vendor.test/guide", title="Product documentation"
    ) == ResearchSourceCategory.MANUFACTURER_DOCUMENTATION


def test_google_search_provider_rejects_missing_or_malformed_citations_safely():
    client = FakeClient(response=grounded_response(chunks=[SimpleNamespace(web=SimpleNamespace(uri="https://x.test", title=None))]))
    provider = GoogleSearchResearchProvider(api_key="test-key", client=client)

    with pytest.raises(ResearchProviderError, match="citations"):
        provider.search("question", max_sources=5)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("429 RESOURCE_EXHAUSTED"), "quota"),
        (RuntimeError("503 UNAVAILABLE"), "temporarily unavailable"),
        (RuntimeError("INVALID_ARGUMENT: search grounding not supported"), "not supported"),
    ],
)
def test_google_search_provider_converts_service_errors_to_safe_failures(error, expected):
    provider = GoogleSearchResearchProvider(api_key="test-key", client=FakeClient(error=error))

    with pytest.raises(ResearchProviderError, match=expected):
        provider.search("question", max_sources=5)


def test_google_search_provider_requires_existing_gemini_credentials(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GoogleSearchResearchProvider(api_key="")

    with pytest.raises(ResearchProviderError, match="GOOGLE_API_KEY"):
        provider.search("question", max_sources=5)


def test_provider_selection_is_opt_in(monkeypatch):
    monkeypatch.delenv("RESEARCH_PROVIDER", raising=False)
    assert research.get_research_provider() is None

    monkeypatch.setenv("RESEARCH_PROVIDER", "google_search")
    assert isinstance(research.get_research_provider(), GoogleSearchResearchProvider)
