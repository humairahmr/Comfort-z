"""Deterministic temperature-unit handling for owner-entered measurements."""

from __future__ import annotations

import re

from comfort_z.models import DirectEnvironmentReading, MonitoringProfile


FAHRENHEIT_REGION_CODES = {"US", "LR", "MM"}
MALAYSIA_LOCATION_TERMS = {"kuching", "sarawak", "malaysia", "kuala lumpur"}
MALAYSIA_TIMEZONES = {"asia/kuching", "asia/kuala_lumpur"}


class TemperatureUnitConfirmationRequired(ValueError):
    """A temperature scale was omitted and no regional default is available."""


def default_temperature_unit(
    profile: MonitoringProfile,
    *,
    locale: str | None = None,
    browser_timezone: str | None = None,
) -> str | None:
    """Return C/F only from stable profile or browser regional metadata, never weather."""
    # The animal's saved context is more reliable than a browser locale. An owner in
    # Malaysia can use an en-US browser without changing the enclosure convention.
    if _is_malaysia_timezone(profile.timezone) or _is_malaysian_location(profile.location_name):
        return "C"
    if _is_malaysia_timezone(browser_timezone):
        return "C"
    region = _locale_region(locale)
    if region:
        return "F" if region in FAHRENHEIT_REGION_CODES else "C"
    return None


def normalize_temperature_reading(
    reading: DirectEnvironmentReading,
    *,
    default_unit: str | None,
) -> tuple[DirectEnvironmentReading, bool]:
    """Canonicalize explicit C/F and fill only an unambiguous regional default.

    The bool indicates that the owner must choose a scale before confirmation.
    """
    if "temperature" not in reading.reading_type.lower():
        return reading, False
    canonical = _canonical_unit(reading.unit)
    if canonical:
        return reading.model_copy(update={"unit": canonical}), False
    if _is_ambiguous_temperature_unit(reading.unit):
        if default_unit in {"C", "F"}:
            return reading.model_copy(update={"unit": default_unit}), False
        return reading, True
    # Preserve explicitly supplied but non-C/F units rather than inventing a conversion.
    return reading, False


def normalize_owner_temperature_reading(
    reading: DirectEnvironmentReading,
    profile: MonitoringProfile,
) -> DirectEnvironmentReading:
    normalized, confirmation_required = normalize_temperature_reading(
        reading,
        default_unit=default_temperature_unit(profile),
    )
    if confirmation_required:
        raise TemperatureUnitConfirmationRequired(
            "Choose whether this temperature is in Celsius or Fahrenheit before saving."
        )
    return normalized


def _canonical_unit(unit: str) -> str | None:
    normalized = _normalize_unit_text(unit).replace("°", "")
    if normalized in {"c", "celsius", "degree c", "degrees c", "degree celsius", "degrees celsius"}:
        return "C"
    if normalized in {"f", "fahrenheit", "degree f", "degrees f", "degree fahrenheit", "degrees fahrenheit"}:
        return "F"
    return None


def _is_ambiguous_temperature_unit(unit: str) -> bool:
    return _normalize_unit_text(unit) in {"", "degree", "degrees"}


def _normalize_unit_text(unit: str) -> str:
    return re.sub(r"\s+", " ", (unit or "").replace("°", "").strip().lower())


def _locale_region(locale: str | None) -> str | None:
    if not locale:
        return None
    parts = re.split(r"[-_]", locale)
    return next(
        (part.upper() for part in reversed(parts[1:]) if re.fullmatch(r"[A-Za-z]{2}", part)),
        None,
    )


def _is_malaysia_timezone(timezone_name: str | None) -> bool:
    return (timezone_name or "").strip().lower() in MALAYSIA_TIMEZONES


def _is_malaysian_location(location_name: str | None) -> bool:
    location = (location_name or "").strip().lower()
    return any(term in location for term in MALAYSIA_LOCATION_TERMS)
