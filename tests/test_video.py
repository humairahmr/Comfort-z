from pathlib import Path

from comfort_z.services.video import VideoMonitoringService


class FakeCapture:
    def __init__(self, frames: list[object], timestamps_ms: list[float], opened: bool = True):
        self.frames = iter(frames)
        self.timestamps_ms = iter(timestamps_ms)
        self.current_timestamp = 0.0
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        try:
            frame = next(self.frames)
            self.current_timestamp = next(self.timestamps_ms)
            return True, frame
        except StopIteration:
            return False, None

    def get(self, _property):
        return self.current_timestamp

    def release(self):
        self.released = True


class FakeCv2:
    CAP_PROP_POS_MSEC = 0

    def __init__(self, capture: FakeCapture):
        self.capture = capture

    def VideoCapture(self, _source):
        return self.capture

    def imwrite(self, path: str, _frame):
        Path(path).write_bytes(b"fake-jpeg")
        return True


def test_video_sampling_calls_existing_monitoring_tool_and_keeps_provenance(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object(), object(), object()], [0, 1000, 2500])
    calls = []

    def monitoring_tool(**kwargs):
        calls.append(kwargs)
        assert Path(kwargs["image_path"]).is_file()
        return {"decision": {"alert_status": False}}

    service = VideoMonitoringService(monitoring_tool=monitoring_tool, cv2_module=FakeCv2(capture))
    session = service.monitor(
        "raku",
        str(video),
        sample_interval_seconds=2.0,
        animal_name="Raku",
        expected_species="Betta splendens",
    )

    assert [sample.frame_index for sample in session.samples] == [1, 3]
    assert session.samples[1].source_timestamp_seconds == 2.5
    assert "frame=3" in calls[1]["source_info"]
    assert calls[0]["expected_species"] == "Betta splendens"
    assert session.animal_name == "Raku"
    assert session.expected_species == "Betta splendens"
    assert capture.released


def test_video_monitoring_continues_after_one_monitoring_failure(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object(), object()], [0, 3000])
    call_count = 0

    def monitoring_tool(**_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Gemini unavailable")
        return {"decision": {"alert_status": False}}

    service = VideoMonitoringService(monitoring_tool=monitoring_tool, cv2_module=FakeCv2(capture))
    session = service.monitor("milo", str(video), sample_interval_seconds=1.0)

    assert len(session.samples) == 1
    assert "Gemini unavailable" in session.failures[0]


def test_invalid_video_and_unavailable_webcam_end_safely(tmp_path):
    service = VideoMonitoringService(cv2_module=FakeCv2(FakeCapture([], [], opened=False)))
    missing = service.monitor("milo", str(tmp_path / "missing.mp4"))
    webcam = service.monitor("milo", 0)

    assert missing.ended_reason == "invalid_source"
    assert webcam.ended_reason == "source_unavailable"


def test_stop_ends_a_session_normally(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object(), object()], [0, 3000])

    def monitoring_tool(**_kwargs):
        service.stop()
        return {"decision": {"alert_status": False}}

    service = VideoMonitoringService(monitoring_tool=monitoring_tool, cv2_module=FakeCv2(capture))
    session = service.monitor("milo", str(video), sample_interval_seconds=1.0)

    assert len(session.samples) == 1
    assert session.ended_reason == "stopped"
    assert capture.released
