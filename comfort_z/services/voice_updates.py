"""Bounded server-side transcription and review-only OwnerUpdate voice drafts."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from comfort_z.models import (
    MonitoringProfile,
    OwnerUpdate,
    VoiceOwnerUpdateDraftBatch,
    VoiceOwnerUpdateDraftResponse,
)
from comfort_z.services.orchestration import MonitoringProfileNotFoundError
from comfort_z.services.repository import MonitoringStateRepository, get_monitoring_state_repository
from comfort_z.services.temperature_units import default_temperature_unit, normalize_temperature_reading


MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_RECORDING_DURATION_MS = 60_000
MAX_TRANSCRIPT_CHARACTERS = 2_000
ALLOWED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
}
DEFAULT_TRANSCRIPTION_MODEL = "gemini-3.5-transcribe"

_NORMALIZATION_PROMPT = """You convert one owner-recorded animal-care transcript into a small list of
structured review drafts. This is not a diagnosis and does not create monitoring evidence.
Extract each independent care fact separately, using only these categories: measurement,
feeding, care, appetite, behavior, availability, note. Never invent numeric readings.

For measurement, include reading_type and numeric value only when spoken. Preserve an explicit
Celsius/Fahrenheit unit as C/F. If the owner says only "degrees" or gives a temperature number
without a scale, set unit to "degrees" so the server can use regional_temperature_unit when
supplied; otherwise retain "degrees", set unit_confirmation_required true, and add a concise
review_warning asking the owner to choose Celsius or Fahrenheit.
For non-measurements, include a concise owner-attributed note. Resolve relative time only when
the supplied capture time and profile timezone make it unambiguous. If an exact time is genuinely
ambiguous, set occurred_at to null and add a review_warning; the owner must choose the time before
saving. Return at most five drafts. Do not diagnose or claim that the information was visually
observed.
"""


class VoiceUpdateError(ValueError):
    """A safe owner-facing voice input validation error."""


class VoiceUpdateUnavailableError(RuntimeError):
    """Gemini transcription or normalization could not complete safely."""


class VoiceUpdateService:
    """Use temporary Gemini Files audio only long enough to produce review drafts."""

    def __init__(
        self,
        *,
        client=None,
        transcription_model: str | None = None,
        normalization_model: str | None = None,
    ) -> None:
        self.transcription_model = transcription_model or os.getenv(
            "VOICE_TRANSCRIPTION_MODEL", DEFAULT_TRANSCRIPTION_MODEL
        )
        self.normalization_model = normalization_model or os.getenv(
            "GEMINI_MODEL", "gemini-3.5-flash"
        )
        if client is not None:
            self.client = client
            return
        if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true":
            raise VoiceUpdateUnavailableError(
                "Voice transcription is unavailable in the current server configuration."
            )
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise VoiceUpdateUnavailableError("Voice transcription is not configured.")
        self.client = genai.Client(api_key=api_key)

    def create_drafts(
        self,
        *,
        profile: MonitoringProfile,
        audio_bytes: bytes,
        mime_type: str,
        capture_timestamp: datetime,
        capture_duration_ms: int,
        browser_timezone: str | None = None,
        locale: str | None = None,
    ) -> VoiceOwnerUpdateDraftResponse:
        clean_mime_type = _validate_audio(audio_bytes, mime_type, capture_duration_ms)
        if capture_timestamp.tzinfo is None:
            raise VoiceUpdateError("The recording time must include a timezone.")
        transcript = self._transcribe(audio_bytes, clean_mime_type)
        try:
            batch = self._normalize(
                transcript=transcript,
                profile=profile,
                capture_timestamp=capture_timestamp.astimezone(timezone.utc),
                browser_timezone=browser_timezone,
                locale=locale,
            )
        except VoiceUpdateUnavailableError:
            # A valid transcript is still useful to the owner. Return no drafts rather than
            # fabricating a fallback, so the UI can offer a typed-update path safely.
            return VoiceOwnerUpdateDraftResponse(
                transcript=transcript,
                drafts=[],
                review_warnings=[
                    "Comfort-z could not safely turn this transcript into care updates. "
                    "Copy it into a typed update instead."
                ],
            )
        _validate_drafts_for_confirmation(batch, profile.animal_id)
        return VoiceOwnerUpdateDraftResponse(
            transcript=transcript,
            drafts=batch.drafts,
            review_warnings=batch.review_warnings,
        )

    def _transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        uploaded_name: str | None = None
        try:
            uploaded = self.client.files.upload(
                file=BytesIO(audio_bytes),
                config=types.UploadFileConfig(mime_type=mime_type, display_name="comfort-z-owner-update"),
            )
            uploaded_name = getattr(uploaded, "name", None)
            uploaded_uri = getattr(uploaded, "uri", None)
            if not uploaded_uri:
                raise VoiceUpdateUnavailableError("Voice transcription did not receive the temporary audio.")
            interaction = self.client.interactions.create(
                model=self.transcription_model,
                input=[{"type": "audio", "uri": uploaded_uri, "mime_type": mime_type}],
                store=False,
            )
            transcript = str(getattr(interaction, "output_text", "") or "").strip()
            if not transcript:
                raise VoiceUpdateUnavailableError("Voice transcription did not return any text.")
            if len(transcript) > MAX_TRANSCRIPT_CHARACTERS:
                raise VoiceUpdateError("The recording produced too much text. Please record a shorter update.")
            return transcript
        except (VoiceUpdateError, VoiceUpdateUnavailableError):
            raise
        except Exception as error:
            raise VoiceUpdateUnavailableError("Voice transcription is temporarily unavailable.") from error
        finally:
            if uploaded_name:
                try:
                    self.client.files.delete(name=uploaded_name)
                except Exception:
                    # The audio is already out of process scope. Do not mask the useful result/error.
                    pass

    def _normalize(
        self,
        *,
        transcript: str,
        profile: MonitoringProfile,
        capture_timestamp: datetime,
        browser_timezone: str | None,
        locale: str | None,
    ) -> VoiceOwnerUpdateDraftBatch:
        try:
            profile_timezone = ZoneInfo(profile.timezone)
        except Exception:
            profile_timezone = timezone.utc
        context = {
            "animal": {
                "animal_id": profile.animal_id,
                "animal_name": profile.animal_name,
                "expected_species": profile.expected_species,
            },
            "capture_timestamp_utc": capture_timestamp.isoformat(),
            "capture_time_in_profile_timezone": capture_timestamp.astimezone(profile_timezone).isoformat(),
            "profile_timezone": profile.timezone,
            "browser_timezone": browser_timezone,
            "locale": locale,
            "regional_temperature_unit": default_temperature_unit(
                profile, locale=locale, browser_timezone=browser_timezone
            ),
            "transcript": transcript,
        }
        try:
            response = self.client.models.generate_content(
                model=self.normalization_model,
                contents=[_NORMALIZATION_PROMPT, json.dumps(context, ensure_ascii=False)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=VoiceOwnerUpdateDraftBatch,
                    temperature=0.0,
                ),
            )
            if not response.text:
                raise VoiceUpdateUnavailableError("Voice update interpretation did not return drafts.")
            batch = VoiceOwnerUpdateDraftBatch.model_validate_json(response.text)
            return _normalize_draft_temperature_units(
                batch,
                profile=profile,
                locale=locale,
                browser_timezone=browser_timezone,
            )
        except VoiceUpdateUnavailableError:
            raise
        except Exception as error:
            raise VoiceUpdateUnavailableError(
                "Voice update interpretation is temporarily unavailable. Your transcript was not saved."
            ) from error


def _validate_audio(audio_bytes: bytes, mime_type: str, capture_duration_ms: int) -> str:
    clean_mime_type = (mime_type or "").split(";", 1)[0].strip().lower()
    if clean_mime_type not in ALLOWED_AUDIO_MIME_TYPES:
        raise VoiceUpdateError("This recording format is not supported. Please use a current browser or add the update manually.")
    if not audio_bytes:
        raise VoiceUpdateError("The recording was empty. Please try again.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise VoiceUpdateError("The recording is too large. Please keep the update under one minute.")
    if not 1 <= capture_duration_ms <= MAX_RECORDING_DURATION_MS:
        raise VoiceUpdateError("Voice updates must be between one millisecond and one minute long.")
    return clean_mime_type


def _validate_drafts_for_confirmation(batch: VoiceOwnerUpdateDraftBatch, animal_id: str) -> None:
    for draft in batch.drafts:
        if draft.occurred_at is None:
            continue
        OwnerUpdate(
            animal_id=animal_id,
            category=draft.category,
            occurred_at=draft.occurred_at,
            note=draft.note,
            reading=draft.reading,
            input_method="voice",
        )


def _normalize_draft_temperature_units(
    batch: VoiceOwnerUpdateDraftBatch,
    *,
    profile: MonitoringProfile,
    locale: str | None,
    browser_timezone: str | None,
) -> VoiceOwnerUpdateDraftBatch:
    default_unit = default_temperature_unit(
        profile, locale=locale, browser_timezone=browser_timezone
    )
    drafts = []
    for draft in batch.drafts:
        if draft.reading is None:
            drafts.append(draft)
            continue
        reading, confirmation_required = normalize_temperature_reading(
            draft.reading, default_unit=default_unit
        )
        warning = draft.review_warning
        if confirmation_required:
            unit_warning = "Choose Celsius or Fahrenheit before saving this temperature."
            warning = f"{warning} {unit_warning}".strip() if warning else unit_warning
        elif _is_unit_confirmation_warning(warning):
            # Gemini may conservatively request a unit even though the server has
            # resolved an unambiguous profile-based default. Do not retain a stale
            # confirmation warning beside a canonical C/F reading.
            warning = None
        drafts.append(draft.model_copy(update={
            "reading": reading,
            "unit_confirmation_required": confirmation_required,
            "review_warning": warning,
        }))
    return batch.model_copy(update={"drafts": drafts})


def _is_unit_confirmation_warning(warning: str | None) -> bool:
    normalized = (warning or "").lower()
    return "celsius" in normalized and "fahrenheit" in normalized


def create_voice_owner_update_drafts(
    animal_id: str,
    *,
    audio_bytes: bytes,
    mime_type: str,
    capture_timestamp: datetime,
    capture_duration_ms: int,
    browser_timezone: str | None = None,
    locale: str | None = None,
    state_repository: MonitoringStateRepository | None = None,
    service: VoiceUpdateService | None = None,
) -> VoiceOwnerUpdateDraftResponse:
    """Build transient voice drafts for an existing animal without persisting anything."""
    state = state_repository or get_monitoring_state_repository()
    profile = state.get_profile(animal_id.strip())
    if profile is None:
        raise MonitoringProfileNotFoundError(
            f"No monitoring profile exists for animal {animal_id!r}."
        )
    return (service or VoiceUpdateService()).create_drafts(
        profile=profile,
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        capture_timestamp=capture_timestamp,
        capture_duration_ms=capture_duration_ms,
        browser_timezone=browser_timezone,
        locale=locale,
    )
