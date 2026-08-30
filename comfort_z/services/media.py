"""Bounded local/demo media storage behind opaque server-managed references."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from uuid import uuid4


MAX_PROFILE_PHOTO_BYTES = 5 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024


class MediaStorageError(ValueError):
    """A safe validation or storage failure for owner-uploaded media."""


@dataclass(frozen=True)
class StoredMedia:
    reference: str
    display_name: str
    content_type: str


_MEDIA_TYPES = {
    "profile-photo": {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    },
    "video": {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
    },
}
_REFERENCE_PATTERN = re.compile(r"^(profile-photo|video)/([0-9a-f]{32})(\.[a-z0-9]+)$")


class LocalMediaStore:
    """Store only validated uploads under a generated name within one app-owned root."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getenv("LOCAL_MEDIA_DIR", "data/media")).resolve()

    def save_profile_photo(
        self, content: bytes, *, content_type: str, original_name: str | None
    ) -> StoredMedia:
        self._validate_image(content, content_type, original_name)
        return self._save("profile-photo", content, content_type, original_name)

    def save_video(
        self, content: bytes, *, content_type: str, original_name: str | None
    ) -> StoredMedia:
        self._validate_video(content, content_type, original_name)
        return self._save("video", content, content_type, original_name)

    def resolve(self, reference: str) -> Path:
        kind, _token, _suffix = self._parse_reference(reference)
        path = (self.root / PurePosixPath(reference)).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise MediaStorageError("Media reference is invalid.") from error
        if not path.is_file():
            raise MediaStorageError("Uploaded media is not available.")
        if kind not in _MEDIA_TYPES:
            raise MediaStorageError("Media reference is invalid.")
        return path

    def public_url(self, reference: str) -> str:
        kind, token, suffix = self._parse_reference(reference)
        return f"/media/{kind}/{token}{suffix}"

    def remove(self, reference: str) -> None:
        """Remove only one generated object; never accept a user-controlled path."""
        try:
            path = (self.root / PurePosixPath(reference)).resolve()
            path.relative_to(self.root)
        except (MediaStorageError, ValueError):
            return
        path.unlink(missing_ok=True)

    def _save(
        self, kind: str, content: bytes, content_type: str, original_name: str | None
    ) -> StoredMedia:
        suffix = _MEDIA_TYPES[kind][content_type]
        reference = f"{kind}/{uuid4().hex}{suffix}"
        destination = (self.root / PurePosixPath(reference)).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return StoredMedia(
            reference=reference,
            display_name=_safe_display_name(original_name, suffix),
            content_type=content_type,
        )

    def _validate_image(self, content: bytes, content_type: str, original_name: str | None) -> None:
        self._validate_size(content, MAX_PROFILE_PHOTO_BYTES, "Profile photo")
        self._validate_type("profile-photo", content_type, original_name)
        signatures = {
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
        }
        if not signatures.get(content_type, False):
            raise MediaStorageError("Profile photo content does not match its image type.")

    def _validate_video(self, content: bytes, content_type: str, original_name: str | None) -> None:
        self._validate_size(content, MAX_VIDEO_UPLOAD_BYTES, "Video")
        self._validate_type("video", content_type, original_name)
        signatures = {
            "video/mp4": len(content) >= 12 and content[4:8] == b"ftyp",
            "video/quicktime": len(content) >= 12 and content[4:8] == b"ftyp",
            "video/webm": content.startswith(b"\x1aE\xdf\xa3"),
        }
        if not signatures.get((content_type or "").lower().split(";", 1)[0].strip(), False):
            raise MediaStorageError("Video content does not match its video type.")

    @staticmethod
    def _validate_size(content: bytes, maximum: int, label: str) -> None:
        if not content:
            raise MediaStorageError(f"{label} upload is empty.")
        if len(content) > maximum:
            raise MediaStorageError(f"{label} upload exceeds the allowed size.")

    @staticmethod
    def _validate_type(kind: str, content_type: str, original_name: str | None) -> None:
        allowed = _MEDIA_TYPES[kind]
        normalized_type = (content_type or "").lower().split(";", 1)[0].strip()
        if normalized_type not in allowed:
            raise MediaStorageError(f"Unsupported {kind.replace('-', ' ')} type.")
        supplied_suffix = PurePosixPath((original_name or "").replace("\\", "/")).suffix.lower()
        if supplied_suffix and supplied_suffix != allowed[normalized_type]:
            raise MediaStorageError(f"{kind.replace('-', ' ').capitalize()} filename does not match its type.")

    @staticmethod
    def _parse_reference(reference: str) -> tuple[str, str, str]:
        match = _REFERENCE_PATTERN.fullmatch(reference or "")
        if not match:
            raise MediaStorageError("Media reference is invalid.")
        return match.group(1), match.group(2), match.group(3)


def get_local_media_store() -> LocalMediaStore:
    return LocalMediaStore()


def is_uploaded_video_reference(reference: str | int) -> bool:
    return isinstance(reference, str) and reference.startswith("video/") and bool(
        _REFERENCE_PATTERN.fullmatch(reference)
    )


def _safe_display_name(original_name: str | None, fallback_suffix: str) -> str:
    candidate = PurePosixPath((original_name or "").replace("\\", "/")).name
    candidate = re.sub(r"[\x00-\x1f<>:\"|?*]", "", candidate).strip()
    if not candidate:
        return f"Uploaded media{fallback_suffix}"
    return candidate[:120]
