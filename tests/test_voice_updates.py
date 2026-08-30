from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from comfort_z.models import MonitoringProfile, MonitoringSourceType
from comfort_z.services.orchestration import MonitoringProfileNotFoundError
from comfort_z.services.voice_updates import (
    MAX_AUDIO_BYTES,
    VoiceUpdateError,
    VoiceUpdateService,
    VoiceUpdateUnavailableError,
    _validate_audio,
    create_voice_owner_update_drafts,
)


CAPTURED_AT = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)


def profile():
    return MonitoringProfile(
        animal_id="raku",
        animal_name="Raku",
        expected_species="Betta splendens",
        monitoring_goal="Keep an eye on Raku.",
        source_reference="Raku.mp4",
        source_type=MonitoringSourceType.VIDEO,
        normal_sampling_interval_seconds=300,
        elevated_sampling_interval_seconds=60,
        daily_sample_budget=12,
        timezone="Asia/Kuala_Lumpur",
    )


def profile_with(**updates):
    values = profile().model_dump()
    values.update(updates)
    return MonitoringProfile(**values)


class FakeFiles:
    def __init__(self):
        self.uploads = []
        self.deleted = []

    def upload(self, *, file, config):
        self.uploads.append((file.read(), config))
        return SimpleNamespace(name="files/temporary-audio", uri="https://example.test/files/temporary-audio")

    def delete(self, *, name):
        self.deleted.append(name)


class FakeInteractions:
    def __init__(self, transcript):
        self.transcript = transcript
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.transcript)


class FakeModels:
    def __init__(self, response_text):
        self.response_text = response_text
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.response_text)


class FakeVoiceClient:
    def __init__(self, transcript, drafts_json):
        self.files = FakeFiles()
        self.interactions = FakeInteractions(transcript)
        self.models = FakeModels(drafts_json)


class ReadOnlyState:
    def __init__(self, saved_profile=None):
        self.saved_profile = saved_profile

    def get_profile(self, animal_id):
        return self.saved_profile if animal_id == "raku" else None

    def save_owner_update(self, *_args, **_kwargs):
        raise AssertionError("voice draft creation must not persist an owner update")


def two_drafts_json():
    return """{
      "drafts": [
        {
          "category": "measurement",
          "occurred_at": "2026-08-30T12:00:00Z",
          "reading": {"reading_type": "water temperature", "value": 27, "unit": "C"}
        },
        {
          "category": "feeding",
          "occurred_at": "2026-08-30T11:30:00Z",
          "note": "Fed Raku."
        }
      ],
      "review_warnings": []
    }"""


def test_voice_service_transcribes_normalizes_and_deletes_temporary_audio():
    client = FakeVoiceClient("Raku's water is 27 degrees and I fed him half an hour ago.", two_drafts_json())
    service = VoiceUpdateService(client=client)

    result = service.create_drafts(
        profile=profile(),
        audio_bytes=b"temporary audio",
        mime_type="audio/webm;codecs=opus",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=3_000,
        browser_timezone="Asia/Kuala_Lumpur",
        locale="en-MY",
    )

    assert result.transcript.startswith("Raku's water")
    assert len(result.drafts) == 2
    assert result.drafts[0].reading.value == 27
    assert result.drafts[1].occurred_at == datetime(2026, 8, 30, 11, 30, tzinfo=timezone.utc)
    assert client.interactions.calls[0]["model"] == "gemini-3.5-transcribe"
    assert client.interactions.calls[0]["store"] is False
    assert client.models.calls[0]["model"] == "gemini-3.5-flash"
    assert client.files.deleted == ["files/temporary-audio"]


def test_temporary_audio_is_deleted_when_transcription_fails():
    client = FakeVoiceClient("", two_drafts_json())
    client.interactions.create = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("transient failure"))
    service = VoiceUpdateService(client=client)

    with pytest.raises(VoiceUpdateUnavailableError):
        service.create_drafts(
            profile=profile(),
            audio_bytes=b"temporary audio",
            mime_type="audio/webm",
            capture_timestamp=CAPTURED_AT,
            capture_duration_ms=1_000,
        )

    assert client.files.deleted == ["files/temporary-audio"]


@pytest.mark.parametrize(
    ("case", "mime_type", "duration"),
    [
        ("empty", "audio/webm", 1),
        ("unsupported_type", "text/plain", 1),
        ("too_long", "audio/webm", 60_001),
        ("too_large", "audio/webm", 1),
    ],
)
def test_voice_audio_bounds_reject_before_gemini(case, mime_type, duration):
    audio = {
        "empty": b"",
        "unsupported_type": b"audio",
        "too_long": b"audio",
        "too_large": b"a" * (MAX_AUDIO_BYTES + 1),
    }[case]
    with pytest.raises(VoiceUpdateError):
        _validate_audio(audio, mime_type, duration)


def test_voice_drafts_are_transient_and_unknown_animals_are_rejected():
    client = FakeVoiceClient("Fed Raku.", """{"drafts": [{"category": "feeding", "occurred_at": "2026-08-30T12:00:00Z", "note": "Fed Raku."}]}""")
    result = create_voice_owner_update_drafts(
        "raku",
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=2_000,
        state_repository=ReadOnlyState(profile()),
        service=VoiceUpdateService(client=client),
    )

    assert result.drafts[0].category.value == "feeding"
    with pytest.raises(MonitoringProfileNotFoundError):
        create_voice_owner_update_drafts(
            "missing",
            audio_bytes=b"audio",
            mime_type="audio/webm",
            capture_timestamp=CAPTURED_AT,
            capture_duration_ms=2_000,
            state_repository=ReadOnlyState(),
            service=VoiceUpdateService(client=client),
        )


def test_malformed_or_over_limit_gemini_drafts_are_rejected_without_persistence():
    too_many = '{"drafts": [' + ','.join(
        '{"category":"feeding","occurred_at":"2026-08-30T12:00:00Z","note":"Fed Raku."}'
        for _ in range(6)
    ) + ']}'
    service = VoiceUpdateService(client=FakeVoiceClient("Fed Raku.", too_many))

    result = service.create_drafts(
        profile=profile(),
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=1_000,
    )

    assert result.transcript == "Fed Raku."
    assert result.drafts == []
    assert "Copy it into a typed update" in result.review_warnings[0]


def test_ambiguous_time_stays_a_review_requirement():
    drafts = """{
      "drafts": [{
        "category": "appetite",
        "occurred_at": null,
        "note": "Raku did not eat this morning.",
        "review_warning": "Choose the time this happened before saving."
      }]
    }"""
    service = VoiceUpdateService(client=FakeVoiceClient("Raku did not eat this morning.", drafts))

    result = service.create_drafts(
        profile=profile(),
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=1_000,
    )

    assert result.drafts[0].occurred_at is None
    assert "Choose the time" in result.drafts[0].review_warning


@pytest.mark.parametrize(
    ("unit", "expected_unit"),
    [
        ("degrees", "C"),
        ("Fahrenheit", "F"),
        ("Celsius", "C"),
    ],
)
def test_voice_temperature_units_use_kuching_default_or_preserve_explicit_units(unit, expected_unit):
    drafts = f'''{{
      "drafts": [{{
        "category": "measurement",
        "occurred_at": "2026-08-30T12:00:00Z",
        "reading": {{"reading_type": "water temperature", "value": {80 if unit == 'Fahrenheit' else 27}, "unit": "{unit}"}}
      }}]
    }}'''
    service = VoiceUpdateService(client=FakeVoiceClient("Temperature update.", drafts))

    result = service.create_drafts(
        profile=profile_with(location_name="Kuching", timezone="Asia/Kuching"),
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=1_000,
    )

    assert result.drafts[0].reading.unit == expected_unit
    assert result.drafts[0].unit_confirmation_required is False


def test_voice_degrees_use_raku_profile_context_over_browser_locale_and_clear_stale_warning():
    drafts = '''{
      "drafts": [{
        "category": "measurement",
        "occurred_at": "2026-08-30T12:00:00Z",
        "reading": {"reading_type": "water temperature", "value": 33.5, "unit": "degrees"},
        "unit_confirmation_required": true,
        "review_warning": "Please confirm if the temperature is in Celsius or Fahrenheit."
      }]
    }'''
    service = VoiceUpdateService(client=FakeVoiceClient("Raku's water is 33.5 degrees.", drafts))

    result = service.create_drafts(
        profile=profile_with(location_name="Kuching, Sarawak", timezone="Asia/Kuching"),
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=1_000,
        # A browser language is a client preference, not a reason to override the
        # saved Malaysian profile convention.
        locale="en-US",
    )

    draft = result.drafts[0]
    assert draft.reading.unit == "C"
    assert draft.unit_confirmation_required is False
    assert draft.review_warning is None


def test_voice_degrees_use_asia_kuching_when_location_is_absent():
    drafts = '''{
      "drafts": [{
        "category": "measurement",
        "occurred_at": "2026-08-30T12:00:00Z",
        "reading": {"reading_type": "water temperature", "value": 27, "unit": "degrees"}
      }]
    }'''
    service = VoiceUpdateService(client=FakeVoiceClient("The water is 27 degrees.", drafts))

    result = service.create_drafts(
        profile=profile_with(location_name=None, timezone="Asia/Kuching"),
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=1_000,
    )

    assert result.drafts[0].reading.unit == "C"
    assert result.drafts[0].unit_confirmation_required is False


def test_voice_temperature_without_reliable_region_requires_owner_unit_review():
    drafts = '''{
      "drafts": [{
        "category": "measurement",
        "occurred_at": "2026-08-30T12:00:00Z",
        "reading": {"reading_type": "water temperature", "value": 27, "unit": "degrees"}
      }]
    }'''
    service = VoiceUpdateService(client=FakeVoiceClient("The water is 27 degrees.", drafts))

    result = service.create_drafts(
        profile=profile_with(location_name=None, timezone="UTC"),
        audio_bytes=b"audio",
        mime_type="audio/webm",
        capture_timestamp=CAPTURED_AT,
        capture_duration_ms=1_000,
    )

    assert result.drafts[0].reading.unit == "degrees"
    assert result.drafts[0].unit_confirmation_required is True
    assert "Choose Celsius or Fahrenheit" in result.drafts[0].review_warning
