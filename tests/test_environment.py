from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from comfort_z.models import DirectEnvironmentReading, EnvironmentContext
from comfort_z.services.environment import (
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
