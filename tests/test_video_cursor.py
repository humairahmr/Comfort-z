from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from comfort_z.models import MonitoringProfile, MonitoringSourceType
from comfort_z.services.orchestration import monitor_next_window
from comfort_z.services.repository import LocalJsonMonitoringStateRepository
from comfort_z.services.source import ResolvedVideoSource
from comfort_z.services.video import VideoMonitoringService


class SeekableCapture:
    def __init__(self, timestamps_ms, fps=30.0):
        self.timestamps_ms = timestamps_ms
        self.fps = fps
        self.position = 0
        self.current_timestamp = 0.0
        self.released = False

    def isOpened(self):
        return True

    def set(self, property_id, value):
        if property_id == SeekableCv2.CAP_PROP_POS_FRAMES:
            self.position = int(value)
        elif property_id == SeekableCv2.CAP_PROP_POS_MSEC:
            self.position = next(
                (index for index, timestamp in enumerate(self.timestamps_ms) if timestamp >= value),
                len(self.timestamps_ms),
            )
        return True

    def read(self):
        if self.position >= len(self.timestamps_ms):
            return False, None
        self.current_timestamp = self.timestamps_ms[self.position]
        self.position += 1
        return True, object()

    def get(self, property_id):
        if property_id == SeekableCv2.CAP_PROP_POS_MSEC:
            return self.current_timestamp
        if property_id == SeekableCv2.CAP_PROP_POS_FRAMES:
            return self.position
        if property_id == SeekableCv2.CAP_PROP_FPS:
            return self.fps
        return 0

    def release(self):
        self.released = True


class SeekableCv2:
    CAP_PROP_POS_MSEC = 0
    CAP_PROP_POS_FRAMES = 1
    CAP_PROP_FPS = 2

    def __init__(self, timestamps_ms):
        self.timestamps_ms = timestamps_ms
        self.captures = []

    def VideoCapture(self, _source):
        capture = SeekableCapture(self.timestamps_ms)
        self.captures.append(capture)
        return capture

    def imwrite(self, path, _frame):
        Path(path).write_bytes(b"frame")
        return True


class RoundingSeekableCapture(SeekableCapture):
    """Simulate a codec that accepts a frame seek but begins decoding at frame zero."""

    def set(self, property_id, value):
        if property_id == SeekableCv2.CAP_PROP_POS_FRAMES:
            return True
        return super().set(property_id, value)


class RoundingSeekableCv2(SeekableCv2):
    def VideoCapture(self, _source):
        capture = RoundingSeekableCapture(self.timestamps_ms)
        self.captures.append(capture)
        return capture


def profile(source_reference):
    return MonitoringProfile(
        animal_id="demo-animal",
        monitoring_goal="Keep watching the demo.",
        source_reference=source_reference,
        source_type=MonitoringSourceType.VIDEO,
        normal_sampling_interval_seconds=300,
        elevated_sampling_interval_seconds=60,
        daily_sample_budget=5,
        budget_period_date=date(2026, 8, 28),
    )


def test_bounded_video_windows_advance_to_strictly_later_frames_not_cursor_rounding(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    state = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    state.save_profile(profile(str(video)))
    cv2_module = SeekableCv2([0.0, 1000 / 30, 2000 / 30])
    seen = []
    service = VideoMonitoringService(
        monitoring_tool=lambda **kwargs: seen.append(kwargs["source_info"]) or {"decision": {}},
        cv2_module=cv2_module,
    )
    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

    first = monitor_next_window(
        "demo-animal", window_max_samples=1, state_repository=state, video_service=service, now=now
    )
    first_profile = state.get_profile("demo-animal")
    second = monitor_next_window(
        "demo-animal", window_max_samples=1, state_repository=state, video_service=service, now=now
    )
    second_profile = state.get_profile("demo-animal")

    assert "source_frame=0; position=0.00s" in seen[0]
    assert "source_frame=1; position=0.03s" in seen[1]
    assert first_profile.source_cursor_frame_index == 1
    assert second_profile.source_cursor_frame_index == 2
    assert first.source_cursor_seconds == 1 / 30
    assert second.source_cursor_seconds == 2 / 30
    assert second.source_cursor_seconds > first.source_cursor_seconds
    assert cv2_module.captures[1].position == 2


def test_failed_attempt_advances_video_cursor_and_end_of_video_is_explicit(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    state = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    state.save_profile(profile(str(video)))
    cv2_module = SeekableCv2([0.0])
    service = VideoMonitoringService(
        monitoring_tool=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("analysis failed")),
        cv2_module=cv2_module,
    )
    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

    failed = monitor_next_window(
        "demo-animal", window_max_samples=1, state_repository=state, video_service=service, now=now
    )
    after_failure = state.get_profile("demo-animal")
    end = monitor_next_window(
        "demo-animal", window_max_samples=1, state_repository=state, video_service=service, now=now
    )
    after_end = state.get_profile("demo-animal")

    assert failed.session.attempted_samples == 1
    assert after_failure.source_cursor_frame_index == 1
    assert end.ended_reason == "end_of_video"
    assert end.active is False
    assert after_end.active is False


def test_frame_cursor_decodes_past_a_rounded_seek_before_sampling(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"not-read-by-fake-capture")
    state = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    state.save_profile(profile(str(video)))
    cv2_module = RoundingSeekableCv2([0.0, 1000 / 30, 2000 / 30])
    seen = []
    service = VideoMonitoringService(
        monitoring_tool=lambda **kwargs: seen.append(kwargs["source_info"]) or {"decision": {}},
        cv2_module=cv2_module,
    )
    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

    monitor_next_window(
        "demo-animal", window_max_samples=1, state_repository=state, video_service=service, now=now
    )
    monitor_next_window(
        "demo-animal", window_max_samples=1, state_repository=state, video_service=service, now=now
    )

    assert "source_frame=0; position=0.00s" in seen[0]
    assert "source_frame=1; position=0.03s" in seen[1]


def test_gcs_materialized_video_uses_the_same_frame_cursor_semantics(tmp_path):
    local_download = tmp_path / "download.mp4"
    local_download.write_bytes(b"not-read-by-fake-capture")
    source_uri = "gs://private-media/demo.mp4"
    state = LocalJsonMonitoringStateRepository(tmp_path / "monitoring_state.json")
    state.save_profile(profile(source_uri))
    cv2_module = SeekableCv2([0.0, 1000 / 30])
    service = VideoMonitoringService(
        monitoring_tool=lambda **_kwargs: {"decision": {}}, cv2_module=cv2_module
    )

    @contextmanager
    def materialized_source(source):
        assert source == source_uri
        yield ResolvedVideoSource(str(local_download), source_uri)

    now = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    monitor_next_window(
        "demo-animal",
        window_max_samples=1,
        state_repository=state,
        video_service=service,
        source_resolver=materialized_source,
        now=now,
    )
    monitor_next_window(
        "demo-animal",
        window_max_samples=1,
        state_repository=state,
        video_service=service,
        source_resolver=materialized_source,
        now=now,
    )

    saved = state.get_profile("demo-animal")
    assert saved.source_reference == source_uri
    assert saved.source_cursor_frame_index == 2
