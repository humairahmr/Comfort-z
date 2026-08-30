from pathlib import Path

import pytest

from comfort_z.services.video import CameraCaptureError, VideoMonitoringService


class FakeCapture:
    def __init__(self, frames: list[object], timestamps_ms: list[float], opened: bool = True):
        self.frames = iter(frames)
        self.timestamps_ms = iter(timestamps_ms)
        self.current_timestamp = 0.0
        self.opened = opened
        self.released = False
        self.seek_calls = []

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

    def set(self, property_id, value):
        self.seek_calls.append((property_id, value))
        return True

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

    def imencode(self, _extension, _frame):
        class Encoded:
            def tobytes(self):
                return b"\xff\xd8preview-jpeg\xff\xd9"

        return True, Encoded()


class SequenceCv2(FakeCv2):
    def __init__(self, captures):
        self.captures = iter(captures)

    def VideoCapture(self, _source):
        return next(self.captures)


class FakeImageFrame:
    def __init__(self, maximum: float):
        self.size = 12
        self._maximum = maximum

    def max(self):
        return self._maximum


class TransientGeminiError(RuntimeError):
    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


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


def test_webcam_warmup_discards_startup_frames_and_uses_a_later_usable_frame():
    black = FakeImageFrame(0)
    valid = FakeImageFrame(32)
    capture = FakeCapture([black, black, black, black, valid], [0, 0, 0, 0, 0])
    calls = []
    service = VideoMonitoringService(
        monitoring_tool=lambda **kwargs: calls.append(kwargs) or {"decision": {}},
        cv2_module=FakeCv2(capture),
    )

    session = service.monitor("milo", 1, max_samples=1)

    assert len(calls) == 1
    assert session.attempted_samples == 1
    assert session.samples[0].frame_index == 5
    assert "position=live" in calls[0]["source_info"]
    assert capture.released


def test_all_black_webcam_frames_stop_without_a_gemini_attempt():
    capture = FakeCapture([FakeImageFrame(0)] * 7, [0] * 7)
    calls = []
    service = VideoMonitoringService(
        monitoring_tool=lambda **kwargs: calls.append(kwargs) or {"decision": {}},
        cv2_module=FakeCv2(capture),
    )

    session = service.monitor("milo", 1, max_samples=1)

    assert calls == []
    assert session.attempted_samples == 0
    assert session.ended_reason == "unusable_frame"
    assert "effectively black" in session.failures[0]
    assert capture.released


def test_webcam_snapshot_uses_warmup_and_never_calls_monitoring_tool():
    capture = FakeCapture([FakeImageFrame(0)] * 3 + [FakeImageFrame(48)], [0] * 4)
    service = VideoMonitoringService(
        monitoring_tool=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not monitor")),
        cv2_module=FakeCv2(capture),
    )

    assert service.capture_webcam_snapshot(1) == b"\xff\xd8preview-jpeg\xff\xd9"
    assert capture.released


def test_webcam_snapshot_failed_read_is_a_controlled_error_and_releases_capture():
    capture = FakeCapture([], [])
    service = VideoMonitoringService(cv2_module=FakeCv2(capture))

    with pytest.raises(CameraCaptureError, match="bounded retries"):
        service.capture_webcam_snapshot(0)

    assert capture.released


def test_webcam_snapshot_reopens_once_after_a_transient_failure_then_succeeds():
    first = FakeCapture([], [], opened=False)
    second = FakeCapture([FakeImageFrame(48)] * 4, [0] * 4)
    service = VideoMonitoringService(cv2_module=SequenceCv2([first, second]))

    jpeg = service.capture_webcam_snapshot(1)

    assert jpeg == b"\xff\xd8preview-jpeg\xff\xd9"
    assert first.released
    assert second.released


def test_webcam_snapshot_returns_controlled_error_when_both_fresh_attempts_fail():
    first = FakeCapture([], [], opened=False)
    second = FakeCapture([FakeImageFrame(0)] * 7, [0] * 7)
    service = VideoMonitoringService(cv2_module=SequenceCv2([first, second]))

    with pytest.raises(CameraCaptureError, match="bounded retries"):
        service.capture_webcam_snapshot(1)

    assert first.released
    assert second.released


def test_webcam_snapshot_rejects_black_frame_and_never_returns_jpeg():
    capture = FakeCapture([FakeImageFrame(0)] * 7, [0] * 7)
    service = VideoMonitoringService(cv2_module=FakeCv2(capture))

    with pytest.raises(CameraCaptureError, match="bounded retries"):
        service.capture_webcam_snapshot(0)

    assert capture.released


def test_webcam_snapshot_rejects_invalid_jpeg_output():
    class InvalidEncodingCv2(FakeCv2):
        def imencode(self, _extension, _frame):
            class Encoded:
                def tobytes(self):
                    return b"not-a-jpeg"

            return True, Encoded()

    capture = FakeCapture([FakeImageFrame(48)] * 4, [0] * 4)
    service = VideoMonitoringService(cv2_module=InvalidEncodingCv2(capture))

    with pytest.raises(CameraCaptureError, match="bounded retries"):
        service.capture_webcam_snapshot(0)

    assert capture.released


def test_webcam_snapshot_read_timeout_releases_capture_and_returns_controlled_error():
    class BlockingCapture(FakeCapture):
        def __init__(self):
            super().__init__([], [])
            from threading import Event

            self.unblock = Event()

        def read(self):
            self.unblock.wait(1)
            return False, None

        def release(self):
            self.released = True
            self.unblock.set()

    capture = BlockingCapture()
    service = VideoMonitoringService(cv2_module=FakeCv2(capture))

    with pytest.raises(CameraCaptureError, match="bounded retries"):
        service.capture_webcam_snapshot(0, timeout_seconds=0.01)

    assert capture.released


def test_windows_webcam_prefers_directshow_before_default_fallback(monkeypatch):
    class DirectShowCv2(FakeCv2):
        CAP_DSHOW = 700

        def __init__(self, capture):
            super().__init__(capture)
            self.open_calls = []

        def VideoCapture(self, *args):
            self.open_calls.append(args)
            return self.capture

    capture = FakeCapture([FakeImageFrame(48)] * 4, [0] * 4)
    cv2_module = DirectShowCv2(capture)
    monkeypatch.setattr("comfort_z.services.video.platform.system", lambda: "Windows")

    VideoMonitoringService(cv2_module=cv2_module).capture_webcam_snapshot(2)

    assert cv2_module.open_calls == [(2, 700)]


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


def test_video_monitoring_can_start_from_a_persisted_video_cursor(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object()], [5000])
    service = VideoMonitoringService(
        monitoring_tool=lambda **_kwargs: {"decision": {"alert_status": False}},
        cv2_module=FakeCv2(capture),
    )

    service.monitor("milo", str(video), max_samples=1, start_at_seconds=5)

    assert capture.seek_calls == [(FakeCv2.CAP_PROP_POS_MSEC, 5000)]


def test_video_source_label_preserves_original_gcs_provenance(tmp_path):
    video = tmp_path / "download.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object()], [0])
    calls = []
    service = VideoMonitoringService(
        monitoring_tool=lambda **kwargs: calls.append(kwargs) or {"decision": {}},
        cv2_module=FakeCv2(capture),
    )

    session = service.monitor(
        "milo",
        str(video),
        source_label="gs://animal-media/videos/today.mp4",
        max_samples=1,
    )

    assert session.samples[0].source == "gs://animal-media/videos/today.mp4"
    assert "source=gs://animal-media/videos/today.mp4" in calls[0]["source_info"]


def test_max_samples_bounds_attempts_even_when_every_frame_fails(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object()] * 7, [index * 1000 for index in range(7)])
    calls = 0

    def monitoring_tool(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("permanent analysis error")

    service = VideoMonitoringService(monitoring_tool=monitoring_tool, cv2_module=FakeCv2(capture))
    session = service.monitor("milo", str(video), sample_interval_seconds=1.0, max_samples=5)

    assert calls == 5
    assert session.attempted_samples == 5
    assert len(session.samples) == 0
    assert len(session.failures) == 5
    assert session.ended_reason == "max_samples_reached"


def test_quota_error_with_substantial_server_delay_stops_without_retry(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    calls = 0
    sleeps = []

    def monitoring_tool(**_kwargs):
        nonlocal calls
        calls += 1
        raise TransientGeminiError("429 RESOURCE_EXHAUSTED", retry_after_seconds=60)

    service = VideoMonitoringService(
        monitoring_tool=monitoring_tool,
        cv2_module=FakeCv2(FakeCapture([object()], [0])),
        sleep_fn=sleeps.append,
    )
    session = service.monitor("milo", str(video), max_samples=5)

    assert calls == 1
    assert session.attempted_samples == 1
    assert session.ended_reason == "quota_exhausted"
    assert sleeps == []


def test_quota_error_retries_once_after_server_retry_delay(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    calls = 0
    sleeps = []

    def monitoring_tool(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TransientGeminiError("429 RESOURCE_EXHAUSTED", retry_after_seconds=0.75)
        return {"decision": {"alert_status": False}}

    service = VideoMonitoringService(
        monitoring_tool=monitoring_tool,
        cv2_module=FakeCv2(FakeCapture([object()], [0])),
        sleep_fn=sleeps.append,
    )
    session = service.monitor("milo", str(video), max_samples=1)

    assert calls == 2
    assert session.attempted_samples == 1
    assert len(session.samples) == 1
    assert session.ended_reason == "max_samples_reached"
    assert sleeps == [0.75]


def test_service_unavailable_retries_with_bounded_exponential_backoff(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    calls = 0
    sleeps = []

    def monitoring_tool(**_kwargs):
        nonlocal calls
        calls += 1
        raise TransientGeminiError("503 UNAVAILABLE")

    service = VideoMonitoringService(
        monitoring_tool=monitoring_tool,
        cv2_module=FakeCv2(FakeCapture([object()], [0])),
        sleep_fn=sleeps.append,
    )
    session = service.monitor(
        "milo",
        str(video),
        max_transient_retries=2,
        base_retry_delay_seconds=0.25,
    )

    assert calls == 3
    assert session.attempted_samples == 1
    assert session.ended_reason == "service_unavailable"
    assert sleeps == [0.25, 0.5]


def test_server_retry_delay_is_used_and_prior_success_is_preserved(tmp_path):
    video = tmp_path / "animal.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    capture = FakeCapture([object(), object()], [0, 1000])
    calls = 0
    sleeps = []
    persisted_results = []

    def monitoring_tool(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            result = {"observation": {"observation_id": "already-stored"}}
            persisted_results.append(result)
            return result
        raise TransientGeminiError("429 RESOURCE_EXHAUSTED", retry_after_seconds=60)

    service = VideoMonitoringService(
        monitoring_tool=monitoring_tool,
        cv2_module=FakeCv2(capture),
        sleep_fn=sleeps.append,
    )
    session = service.monitor("milo", str(video), sample_interval_seconds=1.0, max_samples=5)

    assert session.attempted_samples == 2
    assert session.ended_reason == "quota_exhausted"
    assert len(session.samples) == 1
    assert session.samples[0].monitoring_result == persisted_results[0]
    assert sleeps == []
