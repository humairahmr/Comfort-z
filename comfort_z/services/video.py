"""OpenCV frame sampling that delegates every observation to the existing tool."""

from __future__ import annotations

from collections.abc import Callable
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
from typing import Any

import cv2

from comfort_z.models import (
    DirectEnvironmentReading,
    EnvironmentContext,
    OwnerUpdate,
    VideoFrameSample,
    VideoMonitoringSession,
)
from comfort_z.tools.monitoring import monitor_animal

MonitoringTool = Callable[..., dict[str, Any]]


class VideoMonitoringService:
    """Sample a local video or webcam without introducing a second AI workflow."""

    def __init__(
        self,
        monitoring_tool: MonitoringTool = monitor_animal,
        cv2_module: Any = cv2,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._monitoring_tool = monitoring_tool
        self._cv2 = cv2_module
        self._sleep = sleep_fn
        self._stop_event = Event()

    def stop(self) -> None:
        """Request a normal stop after the current frame has finished processing."""
        self._stop_event.set()

    def monitor(
        self,
        animal_id: str,
        source: str | int,
        sample_interval_seconds: float = 5.0,
        max_samples: int | None = None,
        animal_name: str | None = None,
        expected_species: str | None = None,
        max_transient_retries: int = 1,
        base_retry_delay_seconds: float = 1.0,
        stop_retry_delay_seconds: float = 30.0,
        start_at_seconds: float = 0.0,
        source_label: str | None = None,
        environment_context: EnvironmentContext | None = None,
        direct_environment_readings: list[DirectEnvironmentReading] | None = None,
        owner_updates: list[OwnerUpdate] | None = None,
        enclosure_type: str | None = None,
        start_frame_index: int = 0,
    ) -> VideoMonitoringSession:
        """Run a resilient sampled monitoring session.

        ``source`` is a local video path or an OpenCV webcam device index such
        as ``0``. Optional animal metadata tells Gemini which known animal to
        look for. Each sampled JPEG is passed to ``monitor_animal``; Gemini,
        storage, comparison, and alerts are not reimplemented here. ``max_samples``
        limits selected-frame attempts, including attempts that fail Gemini analysis.
        """
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be greater than zero.")
        if max_samples is not None and max_samples <= 0:
            raise ValueError("max_samples must be greater than zero when supplied.")
        if max_transient_retries < 0:
            raise ValueError("max_transient_retries cannot be negative.")
        if base_retry_delay_seconds <= 0 or stop_retry_delay_seconds <= 0:
            raise ValueError("Retry delays must be greater than zero.")
        if start_at_seconds < 0:
            raise ValueError("start_at_seconds cannot be negative.")
        if start_frame_index < 0:
            raise ValueError("start_frame_index cannot be negative.")

        self._stop_event.clear()
        is_webcam = isinstance(source, int)
        source_label = source_label or (f"webcam:{source}" if is_webcam else str(Path(source)))
        failures: list[str] = []
        samples: list[VideoFrameSample] = []
        attempted_samples = 0
        last_attempt_source_timestamp_seconds: float | None = None
        last_attempt_source_frame_index: int | None = None
        next_source_cursor_seconds: float | None = None
        ended_reason = "completed"

        if not is_webcam and not Path(source).is_file():
            return VideoMonitoringSession(
                animal_id=animal_id,
                animal_name=animal_name,
                expected_species=expected_species,
                source=source_label,
                attempted_samples=attempted_samples,
                failures=[f"Video file does not exist: {source}"],
                ended_reason="invalid_source",
            )

        capture = self._cv2.VideoCapture(source)
        if not capture.isOpened():
            return VideoMonitoringSession(
                animal_id=animal_id,
                animal_name=animal_name,
                expected_species=expected_species,
                source=source_label,
                attempted_samples=attempted_samples,
                failures=[f"Could not open {source_label}."],
                ended_reason="source_unavailable",
            )

        if not is_webcam and start_frame_index:
            try:
                capture.set(self._cv2.CAP_PROP_POS_FRAMES, start_frame_index)
            except Exception as error:
                capture.release()
                return VideoMonitoringSession(
                    animal_id=animal_id,
                    animal_name=animal_name,
                    expected_species=expected_species,
                    source=source_label,
                    attempted_samples=0,
                    failures=[f"Could not seek {source_label}: {error}"],
                    ended_reason="source_seek_error",
                )
        elif not is_webcam and start_at_seconds:
            try:
                capture.set(self._cv2.CAP_PROP_POS_MSEC, start_at_seconds * 1000)
            except Exception as error:
                capture.release()
                return VideoMonitoringSession(
                    animal_id=animal_id,
                    animal_name=animal_name,
                    expected_species=expected_species,
                    source=source_label,
                    attempted_samples=0,
                    failures=[f"Could not seek {source_label}: {error}"],
                    ended_reason="source_seek_error",
                )

        frame_index = 0
        last_sample_at: float | None = None
        try:
            with TemporaryDirectory(prefix="comfort_z_frames_") as frame_directory:
                while not self._stop_event.is_set():
                    try:
                        readable, frame = capture.read()
                    except Exception as error:
                        failures.append(f"Could not read from {source_label}: {error}")
                        ended_reason = "source_read_error"
                        break
                    if not readable:
                        if frame_index == 0:
                            failures.append(f"No readable frames from {source_label}.")
                            ended_reason = (
                                "end_of_video"
                                if not is_webcam and (start_frame_index or start_at_seconds)
                                else "unreadable_source"
                            )
                        elif is_webcam:
                            failures.append(f"Webcam stream ended at frame {frame_index}.")
                            ended_reason = "stream_ended"
                        break

                    frame_index += 1
                    source_seconds = self._source_time_seconds(capture, is_webcam)
                    source_frame_index = self._source_frame_index(
                        capture, is_webcam, frame_index, start_frame_index
                    )
                    if (
                        not is_webcam
                        and start_frame_index > 0
                        and source_frame_index is not None
                        and source_frame_index < start_frame_index
                    ):
                        # Some codecs seek to an earlier keyframe; decode forward to the cursor.
                        continue
                    if (
                        not is_webcam
                        and start_frame_index == 0
                        and start_at_seconds > 0
                        and source_seconds is not None
                        and source_seconds <= start_at_seconds
                    ):
                        continue
                    sampling_time = source_seconds if source_seconds is not None else monotonic()
                    if (
                        last_sample_at is not None
                        and sampling_time - last_sample_at < sample_interval_seconds
                    ):
                        continue
                    last_sample_at = sampling_time
                    if max_samples is not None and attempted_samples >= max_samples:
                        ended_reason = "max_samples_reached"
                        break
                    attempted_samples += 1
                    last_attempt_source_timestamp_seconds = source_seconds
                    last_attempt_source_frame_index = source_frame_index
                    if source_seconds is not None:
                        next_source_cursor_seconds = source_seconds + self._frame_step_seconds(
                            capture
                        )

                    frame_path = Path(frame_directory) / f"frame_{frame_index:06d}.jpg"
                    if not self._cv2.imwrite(str(frame_path), frame):
                        failures.append(f"Could not encode sampled frame {frame_index}.")
                        if max_samples is not None and attempted_samples >= max_samples:
                            ended_reason = "max_samples_reached"
                            break
                        continue

                    source_info = self._source_info(
                        source_label, frame_index, source_seconds, source_frame_index
                    )
                    result, failure, transient_end_reason = self._monitor_frame_with_retries(
                        animal_id=animal_id,
                        image_path=str(frame_path),
                        source_info=source_info,
                        animal_name=animal_name,
                        expected_species=expected_species,
                        frame_index=frame_index,
                        max_transient_retries=max_transient_retries,
                        base_retry_delay_seconds=base_retry_delay_seconds,
                        stop_retry_delay_seconds=stop_retry_delay_seconds,
                        environment_context=environment_context,
                        direct_environment_readings=direct_environment_readings or [],
                        owner_updates=owner_updates or [],
                        enclosure_type=enclosure_type,
                    )
                    if failure:
                        failures.append(failure)
                    if transient_end_reason:
                        ended_reason = transient_end_reason
                        break
                    if result is None:
                        if max_samples is not None and attempted_samples >= max_samples:
                            ended_reason = "max_samples_reached"
                            break
                        continue

                    samples.append(
                        VideoFrameSample(
                            source=source_label,
                            frame_index=frame_index,
                            source_frame_index=source_frame_index,
                            source_timestamp_seconds=source_seconds,
                            monitoring_result=result,
                        )
                    )
                    if max_samples is not None and attempted_samples >= max_samples:
                        ended_reason = "max_samples_reached"
                        break

                if self._stop_event.is_set():
                    ended_reason = "stopped"
        finally:
            capture.release()

        return VideoMonitoringSession(
            animal_id=animal_id,
            animal_name=animal_name,
            expected_species=expected_species,
            source=source_label,
            attempted_samples=attempted_samples,
            samples=samples,
            failures=failures,
            ended_reason=ended_reason,
            last_attempt_source_timestamp_seconds=last_attempt_source_timestamp_seconds,
            last_attempt_source_frame_index=last_attempt_source_frame_index,
            next_source_cursor_seconds=next_source_cursor_seconds,
        )

    def _source_time_seconds(self, capture: Any, is_webcam: bool) -> float | None:
        if is_webcam:
            return None
        milliseconds = capture.get(self._cv2.CAP_PROP_POS_MSEC)
        return milliseconds / 1000 if milliseconds >= 0 else None

    def _source_frame_index(
        self,
        capture: Any,
        is_webcam: bool,
        local_frame_index: int,
        start_frame_index: int,
    ) -> int | None:
        if is_webcam:
            return None
        try:
            position = capture.get(self._cv2.CAP_PROP_POS_FRAMES)
            if isinstance(position, (int, float)) and math.isfinite(position) and position >= 1:
                return int(position) - 1
        except Exception:
            pass
        return start_frame_index + local_frame_index - 1

    def _frame_step_seconds(self, capture: Any) -> float:
        try:
            fps = capture.get(self._cv2.CAP_PROP_FPS)
            if isinstance(fps, (int, float)) and math.isfinite(fps) and fps > 0:
                return 1 / fps
        except Exception:
            pass
        # A sub-second fallback preserves forward timestamp progression for unusual files.
        return 0.001

    @staticmethod
    def _source_info(
        source: str,
        frame_index: int,
        seconds: float | None,
        source_frame_index: int | None,
    ) -> str:
        position = "live" if seconds is None else f"{seconds:.2f}s"
        source_frame = "unknown" if source_frame_index is None else str(source_frame_index)
        return f"source={source}; frame={frame_index}; source_frame={source_frame}; position={position}"

    def _monitor_frame_with_retries(
        self,
        *,
        animal_id: str,
        image_path: str,
        source_info: str,
        animal_name: str | None,
        expected_species: str | None,
        frame_index: int,
        max_transient_retries: int,
        base_retry_delay_seconds: float,
        stop_retry_delay_seconds: float,
        environment_context: EnvironmentContext | None,
        direct_environment_readings: list[DirectEnvironmentReading],
        owner_updates: list[OwnerUpdate],
        enclosure_type: str | None,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        """Retry only one transient Gemini failure class for this one frame."""
        for retry_number in range(max_transient_retries + 1):
            try:
                return (
                    self._monitoring_tool(
                        animal_id=animal_id,
                        image_path=image_path,
                        source_info=source_info,
                        animal_name=animal_name,
                        expected_species=expected_species,
                        environment_context=environment_context,
                        direct_environment_readings=direct_environment_readings,
                        owner_updates=owner_updates,
                        enclosure_type=enclosure_type,
                    ),
                    None,
                    None,
                )
            except Exception as error:
                transient_kind = self._transient_kind(error)
                if transient_kind is None:
                    return None, f"Frame {frame_index} monitoring failed: {error}", None

                retry_delay = self._retry_delay_seconds(
                    error,
                    retry_number,
                    base_retry_delay_seconds,
                )
                ended_reason = (
                    "quota_exhausted" if transient_kind == "quota" else "service_unavailable"
                )
                if retry_delay >= stop_retry_delay_seconds:
                    return (
                        None,
                        f"Frame {frame_index} {transient_kind} error; server requested "
                        f"retry after {retry_delay:.1f}s, stopping session.",
                        ended_reason,
                    )
                if retry_number >= max_transient_retries:
                    return (
                        None,
                        f"Frame {frame_index} {transient_kind} error after "
                        f"{retry_number + 1} attempt(s): {error}. Stopping session.",
                        ended_reason,
                    )
                self._sleep(retry_delay)

        raise AssertionError("Transient retry loop should always return.")

    @staticmethod
    def _transient_kind(error: Exception) -> str | None:
        raw_message = f"{type(error).__name__} {error}"
        message = raw_message.lower()
        if "429" in message or "resource_exhausted" in message:
            return "quota"
        if "503" in message or "UNAVAILABLE" in raw_message or "statuscode.unavailable" in message:
            return "service"
        return None

    @staticmethod
    def _retry_delay_seconds(
        error: Exception,
        retry_number: int,
        base_retry_delay_seconds: float,
    ) -> float:
        for attribute in ("retry_after_seconds", "retry_after", "retry_delay"):
            value = getattr(error, attribute, None)
            if isinstance(value, (int, float)) and value >= 0:
                return float(value)
            seconds = getattr(value, "seconds", None)
            nanos = getattr(value, "nanos", 0)
            if isinstance(seconds, (int, float)):
                return float(seconds) + float(nanos or 0) / 1_000_000_000

        match = re.search(r"retry (?:after|in)\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b", str(error), re.I)
        if match:
            return float(match.group(1))
        return base_retry_delay_seconds * (2**retry_number)
