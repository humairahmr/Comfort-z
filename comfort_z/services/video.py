"""OpenCV frame sampling that delegates every observation to the existing tool."""

from __future__ import annotations

from collections.abc import Callable
import logging
import math
import platform
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
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
logger = logging.getLogger(__name__)


class CameraCaptureError(RuntimeError):
    """A local webcam could not yield a usable snapshot without calling Gemini."""


def is_valid_jpeg_bytes(value: bytes) -> bool:
    """Reject empty/truncated output before the HTTP layer can claim a JPEG success."""
    return isinstance(value, bytes) and len(value) > 4 and value.startswith(b"\xff\xd8") and value.endswith(b"\xff\xd9")


def is_usable_jpeg_bytes(value: bytes) -> bool:
    """Verify a browser-facing JPEG decodes to a non-empty, non-black image."""
    if not is_valid_jpeg_bytes(value):
        return False
    try:
        import numpy as np

        decoded = cv2.imdecode(np.frombuffer(value, dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.size <= 0:
            return False
        return float(decoded.max()) > VideoMonitoringService.BLACK_FRAME_MAX_PIXEL
    except Exception:
        return False


class VideoMonitoringService:
    """Sample a local video or webcam without introducing a second AI workflow."""

    WEBCAM_WARMUP_FRAMES = 3
    WEBCAM_EXTRA_FRAME_READS = 3
    WEBCAM_SNAPSHOT_TIMEOUT_SECONDS = 8.0
    WEBCAM_SNAPSHOT_MAX_ATTEMPTS = 2
    # Deliberately conservative: this catches a blank startup buffer, not a genuinely dark scene.
    BLACK_FRAME_MAX_PIXEL = 4.0

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

    def capture_webcam_snapshot(
        self, camera_index: int, *, timeout_seconds: float | None = None
    ) -> bytes:
        """Return one local JPEG snapshot after the same bounded camera warm-up.

        This is intentionally separate from ``monitor``: it does not create an
        observation, consume a sample budget, or invoke the monitoring tool.
        """
        if not isinstance(camera_index, int) or isinstance(camera_index, bool) or camera_index < 0:
            raise ValueError("camera_index must be a non-negative integer.")
        timeout = self.WEBCAM_SNAPSHOT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        timeout = min(timeout, self.WEBCAM_SNAPSHOT_TIMEOUT_SECONDS)
        deadline = monotonic() + timeout
        failures: list[str] = []
        for attempt_number in range(1, self.WEBCAM_SNAPSHOT_MAX_ATTEMPTS + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            attempts_remaining = self.WEBCAM_SNAPSHOT_MAX_ATTEMPTS - attempt_number + 1
            attempt_deadline = monotonic() + (remaining / attempts_remaining)
            try:
                jpeg = self._capture_webcam_snapshot_once(camera_index, deadline=attempt_deadline)
                logger.info("Camera preview capture succeeded for camera index %s.", camera_index)
                return jpeg
            except CameraCaptureError as error:
                failures.append(str(error))
                if attempt_number < self.WEBCAM_SNAPSHOT_MAX_ATTEMPTS and deadline - monotonic() > 0:
                    logger.info(
                        "Camera preview capture attempt %s failed; reopening camera index %s once.",
                        attempt_number,
                        camera_index,
                    )
        raise CameraCaptureError(
            "Camera preview could not capture a usable frame after bounded retries."
        ) from (CameraCaptureError(failures[-1]) if failures else None)

    def _capture_webcam_snapshot_once(self, camera_index: int, *, deadline: float) -> bytes:
        """Capture one newly-opened webcam frame, always releasing its handle."""
        capture = self._open_webcam(camera_index, deadline=deadline)
        if capture is None:
            logger.warning("Camera preview open failed for camera index %s.", camera_index)
            raise CameraCaptureError("Camera is unavailable.")
        try:
            warmed, warmup_error = self._warm_up_webcam(capture, deadline=deadline)
            if not warmed:
                logger.warning(
                    "Camera preview warm-up/read failed for camera index %s: %s",
                    camera_index,
                    warmup_error,
                )
                raise CameraCaptureError(warmup_error or "Camera did not provide startup frames.")
            frame, _, frame_error = self._read_usable_webcam_frame(capture, deadline=deadline)
            if frame is None:
                if frame_error and ("black" in frame_error.lower() or "unusable" in frame_error.lower()):
                    logger.warning("Camera preview returned a black/unusable frame for camera index %s.", camera_index)
                else:
                    logger.warning(
                        "Camera preview warm-up/read failed for camera index %s: %s",
                        camera_index,
                        frame_error,
                    )
                raise CameraCaptureError(frame_error or "Camera did not provide a usable frame.")
            try:
                encoded, jpeg = self._cv2.imencode(".jpg", frame)
                jpeg_bytes = bytes(jpeg.tobytes()) if jpeg is not None else b""
            except Exception as error:
                logger.warning("Camera preview JPEG validation failed for camera index %s.", camera_index)
                raise CameraCaptureError("Camera frame could not be encoded.") from error
            if not encoded or not is_valid_jpeg_bytes(jpeg_bytes):
                logger.warning("Camera preview JPEG validation failed for camera index %s.", camera_index)
                raise CameraCaptureError("Camera frame could not be encoded.")
            try:
                decoded = self._decode_preview_jpeg(jpeg_bytes)
            except CameraCaptureError:
                logger.warning("Camera preview JPEG validation failed for camera index %s.", camera_index)
                raise
            usable, reason = self._is_usable_camera_frame(decoded)
            if not usable:
                logger.warning("Camera preview JPEG validation failed for camera index %s.", camera_index)
                raise CameraCaptureError(reason or "Camera preview JPEG is unusable.")
            return jpeg_bytes
        finally:
            capture.release()

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

        capture = self._open_webcam(source) if is_webcam else self._cv2.VideoCapture(source)
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
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
        if is_webcam:
            warmed, warmup_error = self._warm_up_webcam(capture)
            if not warmed:
                capture.release()
                return VideoMonitoringSession(
                    animal_id=animal_id,
                    animal_name=animal_name,
                    expected_species=expected_species,
                    source=source_label,
                    attempted_samples=0,
                    failures=[warmup_error or f"No startup frames from {source_label}."],
                    ended_reason="camera_frame_unavailable",
                )
            frame_index = self.WEBCAM_WARMUP_FRAMES
        last_sample_at: float | None = None
        try:
            with TemporaryDirectory(prefix="comfort_z_frames_") as frame_directory:
                while not self._stop_event.is_set():
                    if is_webcam:
                        frame, consumed_frames, camera_error = self._read_usable_webcam_frame(capture)
                        frame_index += consumed_frames
                        if frame is None:
                            failures.append(camera_error or f"No usable frame from {source_label}.")
                            ended_reason = "unusable_frame"
                            break
                        readable = True
                    else:
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

                    if not is_webcam:
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

    def _warm_up_webcam(
        self, capture: Any, *, deadline: float | None = None
    ) -> tuple[bool, str | None]:
        """Discard a few startup frames; phone cameras commonly expose black buffers first."""
        for warmup_number in range(1, self.WEBCAM_WARMUP_FRAMES + 1):
            try:
                readable, _frame, read_error = self._read_webcam(capture, deadline=deadline)
            except Exception as error:
                return False, f"Could not warm up camera: {error}"
            if read_error:
                return False, read_error
            if not readable:
                return False, f"Camera did not provide startup frame {warmup_number}."
        return True, None

    def _read_usable_webcam_frame(
        self, capture: Any, *, deadline: float | None = None
    ) -> tuple[Any | None, int, str | None]:
        """Read one candidate plus a few replacements without promoting bad frames to Gemini."""
        last_reason: str | None = None
        for attempt in range(1, self.WEBCAM_EXTRA_FRAME_READS + 2):
            try:
                readable, frame, read_error = self._read_webcam(capture, deadline=deadline)
            except Exception as error:
                last_reason = f"Could not read camera frame: {error}"
                continue
            if read_error:
                return None, attempt, read_error
            if not readable:
                last_reason = "Camera did not provide a readable frame."
                continue
            usable, reason = self._is_usable_camera_frame(frame)
            if usable:
                return frame, attempt, None
            last_reason = reason
        return None, self.WEBCAM_EXTRA_FRAME_READS + 1, last_reason or "Camera frame is unavailable."

    def _open_webcam(self, camera_index: int, *, deadline: float | None = None) -> Any | None:
        """Prefer DirectShow for local Windows cameras, then retain OpenCV's default fallback."""
        backends: list[int | None] = [None]
        directshow = getattr(self._cv2, "CAP_DSHOW", None)
        if platform.system() == "Windows" and isinstance(directshow, int):
            backends.insert(0, directshow)
        for backend in backends:
            capture = self._open_webcam_capture(camera_index, backend=backend, deadline=deadline)
            if capture is not None and capture.isOpened():
                return capture
            if capture is not None:
                capture.release()
        return None

    def _open_webcam_capture(
        self, camera_index: int, *, backend: int | None, deadline: float | None
    ) -> Any | None:
        if deadline is None:
            try:
                return (
                    self._cv2.VideoCapture(camera_index, backend)
                    if backend is not None
                    else self._cv2.VideoCapture(camera_index)
                )
            except Exception:
                return None
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        result: list[Any | Exception] = []
        completed = Event()
        expired = Event()
        lock = Lock()

        def open_in_worker() -> None:
            capture = None
            try:
                capture = (
                    self._cv2.VideoCapture(camera_index, backend)
                    if backend is not None
                    else self._cv2.VideoCapture(camera_index)
                )
                with lock:
                    if expired.is_set() and capture is not None:
                        capture.release()
                    else:
                        result.append(capture)
            except Exception as error:
                result.append(error)
            finally:
                completed.set()

        worker = Thread(target=open_in_worker, daemon=True)
        worker.start()
        if not completed.wait(remaining):
            with lock:
                expired.set()
                if result and not isinstance(result[0], Exception):
                    result[0].release()
            return None
        outcome = result[0] if result else None
        return None if isinstance(outcome, Exception) else outcome

    def _read_webcam(
        self, capture: Any, *, deadline: float | None
    ) -> tuple[bool, Any, str | None]:
        """Bound one camera read for snapshot preview without changing normal video sampling."""
        if deadline is None:
            readable, frame = capture.read()
            return readable, frame, None
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False, None, "Camera preview timed out."

        result: list[tuple[bool, Any] | Exception] = []
        completed = Event()

        def read_in_worker() -> None:
            try:
                result.append(capture.read())
            except Exception as error:  # pragma: no cover - exercised through the result branch
                result.append(error)
            finally:
                completed.set()

        worker = Thread(target=read_in_worker, daemon=True)
        worker.start()
        if not completed.wait(remaining):
            # Releasing is the only portable OpenCV signal available to unblock a read.
            capture.release()
            return False, None, "Camera preview timed out while waiting for a frame."
        outcome = result[0] if result else RuntimeError("Camera returned no read result.")
        if isinstance(outcome, Exception):
            return False, None, "Camera did not provide a readable frame."
        readable, frame = outcome
        return bool(readable), frame, None

    def _decode_preview_jpeg(self, jpeg_bytes: bytes) -> Any:
        """Verify the browser-facing JPEG decodes to a usable image before returning 200."""
        decoder = getattr(self._cv2, "imdecode", None)
        if not callable(decoder):
            # Lightweight fake OpenCV modules in unit tests do not implement decoding.
            return object()
        try:
            import numpy as np

            flag = getattr(self._cv2, "IMREAD_COLOR", 1)
            decoded = decoder(np.frombuffer(jpeg_bytes, dtype=np.uint8), flag)
        except Exception as error:
            raise CameraCaptureError("Camera preview JPEG could not be decoded.") from error
        if decoded is None:
            raise CameraCaptureError("Camera preview JPEG could not be decoded.")
        return decoded

    def _is_usable_camera_frame(self, frame: Any) -> tuple[bool, str | None]:
        if frame is None:
            return False, "Camera returned an empty frame."
        size = getattr(frame, "size", None)
        if isinstance(size, (int, float)) and size <= 0:
            return False, "Camera returned an empty frame."
        # Test doubles and non-array frames are accepted. Real OpenCV frames are
        # numpy arrays and support max(), allowing a deliberately narrow black check.
        maximum = getattr(frame, "max", None)
        if callable(maximum):
            try:
                if float(maximum()) <= self.BLACK_FRAME_MAX_PIXEL:
                    return False, "Camera returned an effectively black startup frame."
            except Exception:
                pass
        return True, None

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
