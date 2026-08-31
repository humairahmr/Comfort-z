"""Read-only, range-aware preview access for configured monitoring videos."""

from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path
import re
from typing import BinaryIO, Callable, Iterator

from comfort_z.services.media import (
    MediaStorageError,
    get_local_media_store,
    is_uploaded_video_reference,
)
from comfort_z.services.source import (
    InvalidGoogleCloudStorageUriError,
    is_google_cloud_storage_uri,
    parse_google_cloud_storage_uri,
)


STREAM_CHUNK_BYTES = 256 * 1024
_RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


class VideoPreviewError(RuntimeError):
    """A configured video could not be safely exposed for read-only preview."""


class VideoPreviewSourceUnsupportedError(VideoPreviewError):
    """The configured source is not an opaque upload or private Cloud Storage object."""


class InvalidVideoRangeError(VideoPreviewError, ValueError):
    """An HTTP byte range is malformed or outside the configured video."""


@dataclass(frozen=True)
class VideoByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class VideoPreviewAsset:
    size: int
    content_type: str
    open_reader: Callable[[], BinaryIO]

    def iter_bytes(self, selected_range: VideoByteRange) -> Iterator[bytes]:
        """Yield only the requested interval and always close the underlying reader."""
        reader = self.open_reader()
        try:
            reader.seek(selected_range.start)
            remaining = selected_range.length
            while remaining > 0:
                chunk = reader.read(min(STREAM_CHUNK_BYTES, remaining))
                if not chunk:
                    raise VideoPreviewError("Configured monitoring video ended unexpectedly.")
                remaining -= len(chunk)
                yield chunk
        finally:
            reader.close()


def resolve_video_preview_asset(source_reference: str | int) -> VideoPreviewAsset:
    """Resolve only server-stored video references; arbitrary local paths are forbidden."""
    if is_google_cloud_storage_uri(source_reference):
        return _resolve_cloud_storage_asset(source_reference)
    if is_uploaded_video_reference(source_reference):
        return _resolve_uploaded_asset(source_reference)
    raise VideoPreviewSourceUnsupportedError(
        "Configured monitoring video is not available for browser preview."
    )


def parse_video_range(range_header: str | None, size: int) -> VideoByteRange | None:
    """Parse one RFC 7233 byte range; multipart ranges are intentionally unsupported."""
    if range_header is None:
        return None
    match = _RANGE_PATTERN.fullmatch(range_header.strip())
    if match is None or size <= 0:
        raise InvalidVideoRangeError("Requested video range is invalid.")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise InvalidVideoRangeError("Requested video range is invalid.")

    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise InvalidVideoRangeError("Requested video range is invalid.")
        length = min(suffix_length, size)
        return VideoByteRange(start=size - length, end=size - 1)

    start = int(start_text)
    if start >= size:
        raise InvalidVideoRangeError("Requested video range is outside the video.")
    end = size - 1 if not end_text else min(int(end_text), size - 1)
    if end < start:
        raise InvalidVideoRangeError("Requested video range is invalid.")
    return VideoByteRange(start=start, end=end)


def _default_storage_client() -> object:
    from google.cloud import storage

    return storage.Client()


def _resolve_cloud_storage_asset(source_reference: str) -> VideoPreviewAsset:
    try:
        object_ref = parse_google_cloud_storage_uri(source_reference)
        blob = _default_storage_client().bucket(object_ref.bucket_name).blob(
            object_ref.object_name
        )
        blob.reload()
        size = int(blob.size or 0)
        if size <= 0:
            raise VideoPreviewError("Configured monitoring video is empty.")
        return VideoPreviewAsset(
            size=size,
            content_type=_video_content_type(object_ref.object_name, blob.content_type),
            open_reader=lambda: blob.open("rb", chunk_size=STREAM_CHUNK_BYTES),
        )
    except InvalidGoogleCloudStorageUriError as error:
        raise VideoPreviewSourceUnsupportedError(
            "Configured monitoring video is not available for browser preview."
        ) from error
    except VideoPreviewError:
        raise
    except Exception as error:
        raise VideoPreviewError(
            "Configured monitoring video could not be retrieved."
        ) from error


def _resolve_uploaded_asset(source_reference: str) -> VideoPreviewAsset:
    try:
        path = get_local_media_store().resolve(source_reference)
        size = path.stat().st_size
    except (MediaStorageError, OSError) as error:
        raise VideoPreviewError("Uploaded monitoring video is unavailable.") from error
    if size <= 0:
        raise VideoPreviewError("Uploaded monitoring video is empty.")
    return VideoPreviewAsset(
        size=size,
        content_type=_video_content_type(path.name, None),
        open_reader=lambda: Path(path).open("rb"),
    )


def _video_content_type(name: str, stored_type: str | None) -> str:
    normalized = (stored_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith("video/"):
        return normalized
    guessed = mimetypes.guess_type(name)[0]
    return guessed if guessed and guessed.startswith("video/") else "application/octet-stream"
