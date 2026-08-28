"""Optional outdoor-weather context, kept separate from direct enclosure readings."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from comfort_z.models import DirectEnvironmentReading, EnvironmentContext


class EnvironmentLookupError(RuntimeError):
    """A weather provider could not supply optional context for this monitoring run."""


class EnvironmentProvider(Protocol):
    def get_current_context(
        self,
        *,
        location_name: str | None,
        latitude: float,
        longitude: float,
    ) -> EnvironmentContext:
        """Return current outdoor/local context for known coordinates."""


class OpenMeteoEnvironmentProvider:
    """Small keyless Open-Meteo current-weather adapter."""

    endpoint = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, opener=urlopen, timeout_seconds: float = 5.0) -> None:
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def get_current_context(
        self,
        *,
        location_name: str | None,
        latitude: float,
        longitude: float,
    ) -> EnvironmentContext:
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
                "timezone": "UTC",
            }
        )
        try:
            with self._opener(f"{self.endpoint}?{query}", timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            current = payload["current"]
            observed_at = datetime.fromisoformat(current["time"])
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            code = int(current["weather_code"])
            return EnvironmentContext(
                provider="Open-Meteo",
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
                outdoor_temperature_c=float(current["temperature_2m"]),
                outdoor_humidity_percent=float(current["relative_humidity_2m"]),
                weather_condition=_weather_condition(code),
                observed_at=observed_at,
            )
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            raise EnvironmentLookupError("Outdoor weather context is unavailable.") from error


def missing_direct_reading_requests(
    context: EnvironmentContext | None,
    readings: list[DirectEnvironmentReading],
    enclosure_type: str | None,
) -> list[str]:
    """Request a direct reading only for broadly notable outdoor heat/cold context.

    These are generic environmental prompts, not species thresholds or health claims.
    """
    if context is None or context.outdoor_temperature_c is None or _has_temperature_reading(readings):
        return []
    enclosure = enclosure_type.strip() if enclosure_type else "enclosure"
    if context.outdoor_temperature_c >= 30:
        return [
            f"Outdoor conditions are hot, but the actual {enclosure} temperature is unknown. "
            "Ask the owner for a direct temperature reading."
        ]
    if context.outdoor_temperature_c <= 5:
        return [
            f"Outdoor conditions are cold, but the actual {enclosure} temperature is unknown. "
            "Ask the owner for a direct temperature reading."
        ]
    return []


def _has_temperature_reading(readings: list[DirectEnvironmentReading]) -> bool:
    return any("temperature" in reading.reading_type.lower() for reading in readings)


def _weather_condition(code: int) -> str:
    conditions = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        61: "slight rain",
        63: "moderate rain",
        65: "heavy rain",
        71: "slight snow",
        73: "moderate snow",
        75: "heavy snow",
        80: "rain showers",
        81: "moderate rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
    }
    return conditions.get(code, f"WMO weather code {code}")
