"""Gemini multimodal analysis constrained to non-diagnostic observation data."""
from __future__ import annotations
import mimetypes
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from comfort_z.models import (
    DailyReportNarrative,
    DirectEnvironmentReading,
    EnvironmentContext,
    GeminiObservation,
)

_PROMPT = """You are Comfort-z's visual observation component. Analyze only what is visibly supported by the supplied animal image or short visual input. Return the requested structured observation. Do not diagnose disease or claim certainty. Use wording such as 'potentially concerning', 'visible abnormality', 'consider monitoring', or 'seek professional veterinary advice'. A single uncertain visual observation should usually have severity 'monitor', not 'potentially_concerning'. Set severity using visible evidence only.

Always set animal_visible and observation_status. If the monitored animal is not sufficiently visible, set animal_visible to false and observation_status to animal_not_visible or uncertain. In that case, set species to null, do not infer behaviour from another animal or object, and set severity to monitor rather than normal. These records are provenance only and do not establish that the monitored animal is normal."""

_REPORT_PROMPT = """You are Comfort-z's daily animal-monitoring reporting component. Summarize only the supplied structured observation records; no images are being supplied. Be evidence-based and non-diagnostic. Clearly distinguish valid observations from frames where the monitored animal was not visible or was uncertain. Do not claim that missing visibility means normal behaviour. Describe potentially concerning records and saved alert decisions, meaningful change relative to prior valid records when supplied, and a practical next action. When material saved research context is supplied, summarize it without refetching: treat community sources as anecdotal and never let them override authoritative or professional guidance."""

_OUTDOOR_CONTEXT_PROMPT = """The following is outdoor/local weather context only. It can be supporting context, but must never be treated as the temperature, humidity, or other condition inside an aquarium, terrarium, cage, room, or enclosure. Do not diagnose or make a health claim from outdoor weather alone. Owner-provided direct readings, if supplied, are distinct evidence. If a needed enclosure condition is unknown, state that a direct reading is needed rather than inventing one."""

load_dotenv()

class GeminiVisualAnalyzer:
    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        # The Google GenAI SDK supports either name for Gemini Developer API keys.
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key and os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() != "true":
            raise RuntimeError(
                "Set GEMINI_API_KEY or GOOGLE_API_KEY, or set "
                "GOOGLE_GENAI_USE_VERTEXAI=true with Google Cloud credentials."
            )
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def analyze_file(
        self,
        image_path: str,
        expected_species: str | None = None,
        environment_context: EnvironmentContext | None = None,
        direct_environment_readings: list[DirectEnvironmentReading] | None = None,
    ) -> GeminiObservation:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"Visual input not found: {path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        part = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)
        context = _PROMPT
        if expected_species:
            context += (
                "\n\nThe owner is monitoring a known animal whose expected species is "
                f"{expected_species}. First decide whether that expected animal is visibly "
                "present. Do not replace it with a different species based on another animal "
                "or object in the frame. If evidence for the expected animal is poor, mark it "
                "not visible or uncertain rather than identifying a different species."
            )
        if environment_context:
            context += "\n\n" + _OUTDOOR_CONTEXT_PROMPT
            context += "\nOutdoor/local weather context:\n" + json.dumps(
                environment_context.model_dump(mode="json")
            )
            context += "\nOwner-provided direct readings:\n" + json.dumps(
                [reading.model_dump(mode="json") for reading in direct_environment_readings or []]
            )
        response = self.client.models.generate_content(
            model=self.model,
            contents=[context, part],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiObservation,
                temperature=0.1,
            ),
        )
        if not response.text:
            raise RuntimeError("Gemini returned no structured observation.")
        return GeminiObservation.model_validate_json(response.text)


class GeminiDailyReportGenerator:
    """Use the configured Comfort-z Gemini model to summarize stored, structured history."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key and os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() != "true":
            raise RuntimeError(
                "Set GEMINI_API_KEY or GOOGLE_API_KEY, or set "
                "GOOGLE_GENAI_USE_VERTEXAI=true with Google Cloud credentials."
            )
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()

    def generate(self, structured_history: dict) -> DailyReportNarrative:
        history_json = json.dumps(
            structured_history,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=[_REPORT_PROMPT + "\n\n" + _OUTDOOR_CONTEXT_PROMPT, history_json],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DailyReportNarrative,
                temperature=0.1,
            ),
        )

        if not response.text:
            raise RuntimeError("Gemini returned no structured daily report.")

        return DailyReportNarrative.model_validate_json(response.text)
