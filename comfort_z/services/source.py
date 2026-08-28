"""Resolve private Cloud Storage video URIs without changing monitoring semantics."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Callable, Iterator
from urllib.parse import urlsplit


class VideoSourceResolutionError(RuntimeError):
    """A safe domain-level failure while materializing a video source."""


class InvalidGoogleCloudStorageUriError(VideoSourceResolutionError, ValueError):
    """The supplied gs:// URI does not name one bucket object."""


class GoogleCloudStorageAccessError(VideoSourceResolutionError):
    """The active application identity cannot read the requested object."""


class GoogleCloudStorageDownloadError(VideoSourceResolutionError):
    """Cloud Storage could not provide the requested video object."""


@dataclass(frozen=True)
class GoogleCloudStorageObject:
    bucket_name: str
    object_name: str


@dataclass(frozen=True)
class ResolvedVideoSource:
    """The short-lived OpenCV input and stable provenance label for one source."""

    local_source: str | int
    source_label: str | None = None


def is_google_cloud_storage_uri(source_reference: str | int) -> bool:
    return isinstance(source_reference, str) and source_reference.startswith("gs://")


def parse_google_cloud_storage_uri(uri: str) -> GoogleCloudStorageObject:
    """Validate a gs://bucket/object URI without contacting Cloud Storage."""
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "gs"
        or not parsed.netloc
        or not parsed.path
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidGoogleCloudStorageUriError(
            "Cloud Storage video source must use gs://bucket/object format."
        )
    # Remove only the URI separator; a leading slash is valid object-name data.
    object_name = parsed.path[1:]
    if not object_name:
        raise InvalidGoogleCloudStorageUriError(
            "Cloud Storage video source must include an object name."
        )
    return GoogleCloudStorageObject(bucket_name=parsed.netloc, object_name=object_name)


def _default_storage_client() -> object:
    # Cloud Run supplies Application Default Credentials through its service account.
    from google.cloud import storage

    return storage.Client()


@contextmanager
def resolve_video_source(
    source_reference: str | int,
    *,
    storage_client_factory: Callable[[], object] = _default_storage_client,
) -> Iterator[ResolvedVideoSource]:
    """Yield a local video source, downloading private gs:// objects only when needed.

    Local paths and webcam indices are passed through unchanged. A Cloud Storage
    object is streamed by the client library directly to a securely-created
    temporary file, which is deleted after the caller's bounded operation.
    """
    if not is_google_cloud_storage_uri(source_reference):
        yield ResolvedVideoSource(local_source=source_reference)
        return

    object_ref = parse_google_cloud_storage_uri(source_reference)
    suffix = PurePosixPath(object_ref.object_name).suffix
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            prefix="comfort_z_video_", suffix=suffix, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        client = storage_client_factory()
        blob = client.bucket(object_ref.bucket_name).blob(object_ref.object_name)
        # download_to_filename writes to disk; it does not materialize the video in memory.
        blob.download_to_filename(str(temporary_path))
    except Exception as error:
        _remove_temporary_file(temporary_path)
        raise _cloud_storage_error(error) from error

    try:
        yield ResolvedVideoSource(
            local_source=str(temporary_path), source_label=source_reference
        )
    finally:
        _remove_temporary_file(temporary_path)


def _cloud_storage_error(error: Exception) -> VideoSourceResolutionError:
    name = type(error).__name__.lower()
    status_code = getattr(error, "code", None)
    if callable(status_code):
        status_code = status_code()
    if "notfound" in name or status_code == 404:
        return GoogleCloudStorageDownloadError(
            "The Cloud Storage video source was not found."
        )
    if (
        "forbidden" in name
        or "permissiondenied" in name
        or "unauthorized" in name
        or "credential" in name
        or status_code in {401, 403}
    ):
        return GoogleCloudStorageAccessError(
            "The application identity cannot access the Cloud Storage video source."
        )
    return GoogleCloudStorageDownloadError(
        "The Cloud Storage video source could not be downloaded."
    )


def _remove_temporary_file(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)
