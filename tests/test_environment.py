from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from comfort_z import api
from comfort_z.models import DirectEnvironmentReading, EnvironmentContext
from comfort_z.services.environment import (
    EnvironmentLookupError,
    OpenMeteoEnvironmentProvider,
    missing_direct_reading_requests,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def weather_context(temperature=33.0):
    return EnvironmentContext(
        provider="test-weather",
        location_name="Test location",
        latitude=1.0,
        longitude=2.0,
        outdoor_temperature_c=temperature,
        outdoor_humidity_percent=70,
        weather_condition="clear sky",
        observed_at=datetime(2026, 8, 28, 12, tzinfo=timezone.utc),
    )


def test_open_meteo_provider_returns_structured_outdoor_context_without_a_key():
    captured = {}

    def opener(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return FakeResponse(
            b'{"current":{"time":"2026-08-28T12:00","temperature_2m":31.5,'
            b'"relative_humidity_2m":68,"weather_code":2}}'
        )

    context = OpenMeteoEnvironmentProvider(opener=opener).get_current_context(
        location_name="Test location", latitude=1.0, longitude=2.0
    )

    query = parse_qs(urlsplit(captured["url"]).query)
    assert query["current"] == ["temperature_2m,relative_humidity_2m,weather_code"]
    assert "apikey" not in query
    assert context.outdoor_temperature_c == 31.5
    assert context.outdoor_humidity_percent == 68
    assert context.weather_condition == "partly cloudy"
    assert "not a direct enclosure" in context.context_note


def test_hot_outdoor_weather_requests_direct_enclosure_reading_without_inference():
    requests = missing_direct_reading_requests(weather_context(), [], "aquarium")

    assert requests == [
        "Outdoor conditions are hot, but the actual aquarium temperature is unknown. "
        "Ask the owner for a direct temperature reading."
    ]


def test_owner_direct_temperature_reading_prevents_missing_reading_request():
    requests = missing_direct_reading_requests(
        weather_context(),
        [DirectEnvironmentReading(reading_type="water_temperature", value=26, unit="C")],
        "aquarium",
    )

    assert requests == []


class FakeEnvironmentProvider:
    def __init__(self, context=None, error=None):
        self.context = context
        self.error = error
        self.calls = []

    def get_current_context(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.context


def test_current_environment_endpoint_is_read_only_and_returns_structured_context(monkeypatch):
    provider = FakeEnvironmentProvider(weather_context(31.5))
    monkeypatch.setattr(api, "OpenMeteoEnvironmentProvider", lambda: provider)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("current weather must not read or mutate monitoring state")

    monkeypatch.setattr(api, "get_monitoring_state_repository", forbidden)
    monkeypatch.setattr(api, "monitor_animal", forbidden)
    monkeypatch.setattr(api, "monitor_next_window", forbidden)
    response = TestClient(api.app).get(
        "/environment/current",
        params={"latitude": 1.0, "longitude": 2.0, "location_name": "Test location"},
    )

    assert response.status_code == 200
    assert response.json()["outdoor_temperature_c"] == 31.5
    assert response.json()["outdoor_humidity_percent"] == 70
    assert provider.calls == [
        {"location_name": "Test location", "latitude": 1.0, "longitude": 2.0}
    ]


@pytest.mark.parametrize(
    "parameters",
    [
        {"latitude": -90.1, "longitude": 2.0},
        {"latitude": 90.1, "longitude": 2.0},
        {"latitude": 1.0, "longitude": -180.1},
        {"latitude": 1.0, "longitude": 180.1},
    ],
)
def test_current_environment_endpoint_rejects_invalid_coordinates(parameters):
    response = TestClient(api.app).get("/environment/current", params=parameters)

    assert response.status_code == 422


def test_current_environment_endpoint_returns_safe_unavailable_response(monkeypatch):
    provider = FakeEnvironmentProvider(
        error=EnvironmentLookupError("provider implementation detail")
    )
    monkeypatch.setattr(api, "OpenMeteoEnvironmentProvider", lambda: provider)

    response = TestClient(api.app).get(
        "/environment/current", params={"latitude": 1.0, "longitude": 2.0}
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Outdoor weather context is temporarily unavailable."
    }
