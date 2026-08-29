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


def test_gemini_daily_report_generator_serializes_structured_history_to_json():
    from comfort_z.services.analyzer import GeminiDailyReportGenerator

    captured_kwargs = {}

    def fake_generate_content(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            text="""{
                "overall_activity_behavior": "Animal was monitored over 24h.",
                "notable_changes": [],
                "concerning_observations": [],
                "visibility_data_quality_limitations": "Limited camera angle.",
                "comparison_with_prior_observations": "Consistent with previous records.",
                "recommended_action": "Continue normal monitoring routine."
            }"""
        )

    generator = GeminiDailyReportGenerator.__new__(GeminiDailyReportGenerator)
    generator.model = "gemini-3.5-flash"
    generator.client = SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content))

    structured_history = {
        "animal": {"animal_id": "raku", "animal_name": "Raku"},
        "counts": {"valid": 2, "concerning": 0},
    }
    narrative = generator.generate(structured_history)

    assert "contents" in captured_kwargs
    contents = captured_kwargs["contents"]
    assert len(contents) == 2
    assert isinstance(contents[1], str)
    assert not isinstance(contents[1], dict)
    assert '"animal_id": "raku"' in contents[1]
    assert narrative.overall_activity_behavior == "Animal was monitored over 24h."
