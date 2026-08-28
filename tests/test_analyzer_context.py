from types import SimpleNamespace

from comfort_z.models import DirectEnvironmentReading, EnvironmentContext
from comfort_z.services.analyzer import GeminiVisualAnalyzer


class CapturingModel:
    def __init__(self):
        self.contents = None

    def generate_content(self, **kwargs):
        self.contents = kwargs["contents"]
        return SimpleNamespace(
            text="""{
                "species": "Betta splendens",
                "animal_visible": true,
                "observation_status": "valid",
                "posture": "swimming",
                "activity_level": "moderate",
                "apparent_movement": "moving",
                "confidence": 0.9,
                "behavioral_interpretation": "The expected fish is visible.",
                "uncertainty": "Only one frame was provided.",
                "severity": "normal"
            }"""
        )


def test_expected_species_is_sent_to_gemini_context(tmp_path):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"not-decoded-by-fake-client")
    model = CapturingModel()
    analyzer = GeminiVisualAnalyzer.__new__(GeminiVisualAnalyzer)
    analyzer.model = "gemini-3.5-flash"
    analyzer.client = SimpleNamespace(models=model)

    observation = analyzer.analyze_file(str(image), expected_species="Betta splendens")

    assert "expected species is Betta splendens" in model.contents[0]
    assert observation.species == "Betta splendens"


def test_outdoor_context_is_explicitly_not_treated_as_enclosure_data(tmp_path):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"not-decoded-by-fake-client")
    model = CapturingModel()
    analyzer = GeminiVisualAnalyzer.__new__(GeminiVisualAnalyzer)
    analyzer.model = "gemini-3.5-flash"
    analyzer.client = SimpleNamespace(models=model)
    outdoor_context = EnvironmentContext(
        provider="test-weather",
        location_name="Test location",
        outdoor_temperature_c=33,
        observed_at="2026-08-28T12:00:00Z",
    )

    analyzer.analyze_file(
        str(image),
        environment_context=outdoor_context,
        direct_environment_readings=[
            DirectEnvironmentReading(reading_type="water_temperature", value=26, unit="C")
        ],
    )

    assert "must never be treated as the temperature" in model.contents[0]
    assert "Outdoor/local weather context" in model.contents[0]
    assert "water_temperature" in model.contents[0]
