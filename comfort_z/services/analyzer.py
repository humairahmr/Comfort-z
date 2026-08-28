"""Gemini multimodal analysis constrained to non-diagnostic observation data."""
from __future__ import annotations
import mimetypes
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from comfort_z.models import GeminiObservation

_PROMPT = """You are Comfort-z's visual observation component. Analyze only what is visibly supported by the supplied animal image or short visual input. Return the requested structured observation. Do not diagnose disease or claim certainty. Use wording such as 'potentially concerning', 'visible abnormality', 'consider monitoring', or 'seek professional veterinary advice'. A single uncertain visual observation should usually have severity 'monitor', not 'potentially_concerning'. Set severity using visible evidence only.

Always set animal_visible and observation_status. If the monitored animal is not sufficiently visible, set animal_visible to false and observation_status to animal_not_visible or uncertain. In that case, set species to null, do not infer behaviour from another animal or object, and set severity to monitor rather than normal. These records are provenance only and do not establish that the monitored animal is normal."""

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
