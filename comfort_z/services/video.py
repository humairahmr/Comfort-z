"""OpenCV frame sampling that delegates every observation to the existing tool."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from typing import Any

import cv2

from comfort_z.models import VideoFrameSample, VideoMonitoringSession
from comfort_z.tools.monitoring import monitor_animal

MonitoringTool = Callable[..., dict[str, Any]]


class VideoMonitoringService:
    """Sample a local video or webcam without introducing a second AI workflow."""

    def __init__(
        self,
        monitoring_tool: MonitoringTool = monitor_animal,
        cv2_module: Any = cv2,
    ) -> None:
        self._monitoring_tool = monitoring_tool
        self._cv2 = cv2_module
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
    ) -> VideoMonitoringSession:
        """Run a resilient sampled monitoring session.

        ``source`` is a local video path or an OpenCV webcam device index such
        as ``0``. Optional animal metadata tells Gemini which known animal to
        look for. Each sampled JPEG is passed to ``monitor_animal``; Gemini,
        storage, comparison, and alerts are not reimplemented here.
        """
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be greater than zero.")
        if max_samples is not None and max_samples <= 0:
            raise ValueError("max_samples must be greater than zero when supplied.")

        self._stop_event.clear()
        is_webcam = isinstance(source, int)
        source_label = f"webcam:{source}" if is_webcam else str(Path(source))
        failures: list[str] = []
        samples: list[VideoFrameSample] = []
        ended_reason = "completed"

        if not is_webcam and not Path(source).is_file():
            return VideoMonitoringSession(
                animal_id=animal_id,
                animal_name=animal_name,
                expected_species=expected_species,
                source=source_label,
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
                failures=[f"Could not open {source_label}."],
                ended_reason="source_unavailable",
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
                            ended_reason = "unreadable_source"
                        elif is_webcam:
                            failures.append(f"Webcam stream ended at frame {frame_index}.")
                            ended_reason = "stream_ended"
                        break

                    frame_index += 1
                    source_seconds = self._source_time_seconds(capture, is_webcam)
                    sampling_time = source_seconds if source_seconds is not None else monotonic()
                    if (
                        last_sample_at is not None
                        and sampling_time - last_sample_at < sample_interval_seconds
                    ):
                        continue
                    last_sample_at = sampling_time

                    frame_path = Path(frame_directory) / f"frame_{frame_index:06d}.jpg"
                    if not self._cv2.imwrite(str(frame_path), frame):
                        failures.append(f"Could not encode sampled frame {frame_index}.")
                        continue

                    source_info = self._source_info(source_label, frame_index, source_seconds)
                    try:
                        result = self._monitoring_tool(
                            animal_id=animal_id,
                            image_path=str(frame_path),
                            source_info=source_info,
                            animal_name=animal_name,
                            expected_species=expected_species,
                        )
                    except Exception as error:  # Continue with the next sampled frame.
                        failures.append(f"Frame {frame_index} monitoring failed: {error}")
                        continue

                    samples.append(
                        VideoFrameSample(
                            source=source_label,
                            frame_index=frame_index,
                            source_timestamp_seconds=source_seconds,
                            monitoring_result=result,
                        )
                    )
                    if max_samples is not None and len(samples) >= max_samples:
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
            samples=samples,
            failures=failures,
            ended_reason=ended_reason,
        )

    def _source_time_seconds(self, capture: Any, is_webcam: bool) -> float | None:
        if is_webcam:
            return None
        milliseconds = capture.get(self._cv2.CAP_PROP_POS_MSEC)
        return milliseconds / 1000 if milliseconds >= 0 else None

    @staticmethod
    def _source_info(source: str, frame_index: int, seconds: float | None) -> str:
        position = "live" if seconds is None else f"{seconds:.2f}s"
        return f"source={source}; frame={frame_index}; position={position}"
