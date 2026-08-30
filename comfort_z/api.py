"""Minimal Cloud Run HTTP adapter for the existing Comfort-z ADK tools."""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt, model_validator
from starlette.concurrency import run_in_threadpool

from comfort_z.agent import root_agent
from comfort_z.models import (
    DirectEnvironmentReading,
    MonitoringProfile,
    MonitoringSourceType,
    OwnerUpdateCategory,
    VoiceOwnerUpdateDraftResponse,
)
from comfort_z.services.repository import ObservationRepositoryError, get_monitoring_state_repository
from comfort_z.services.orchestration import (
    MonitoringProfileNotFoundError,
    MonitoringSourceNotConnectedError,
)
from comfort_z.services.video import CameraCaptureError, is_usable_jpeg_bytes
from comfort_z.services.media import (
    MAX_PROFILE_PHOTO_BYTES,
    MAX_VIDEO_UPLOAD_BYTES,
    MediaStorageError,
    get_local_media_store,
)
from comfort_z.services.voice_updates import (
    MAX_AUDIO_BYTES,
    VoiceUpdateError,
    VoiceUpdateUnavailableError,
    create_voice_owner_update_drafts,
)
from comfort_z.services.temperature_units import TemperatureUnitConfirmationRequired
from comfort_z.tools.monitoring import (
    connect_monitoring_source,
    capture_local_camera_preview,
    create_monitoring_profile,
    disconnect_monitoring_source,
    generate_daily_report,
    get_recent_daily_reports,
    get_recent_observations,
    get_recent_owner_updates,
    monitor_animal,
    monitor_next_window,
    pause_monitoring,
    record_owner_update,
    set_profile_location,
    set_profile_photo_reference,
    start_monitoring,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DEMO_VIDEOS_DIR = Path(__file__).resolve().parent.parent / "demo_videos"

app = FastAPI(title="Comfort-z", version="0.1.0")

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class MonitorRequest(BaseModel):
    """Inputs passed unchanged to Comfort-z's existing monitor_animal tool."""

    animal_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    source_info: str | None = None
    animal_name: str | None = None
    expected_species: str | None = None


class MonitoringProfileRequest(BaseModel):
    animal_id: str = Field(min_length=1)
    monitoring_goal: str = Field(min_length=1)
    source_reference: str | int | None = None
    source_type: MonitoringSourceType | None = None
    normal_sampling_interval_seconds: float = Field(default=300.0, gt=0)
    elevated_sampling_interval_seconds: float = Field(default=60.0, gt=0)
    daily_sample_budget: int = Field(default=24, gt=0)
    animal_name: str | None = None
    expected_species: str | None = None
    location_name: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    enclosure_type: str | None = None
    direct_environment_readings: list[DirectEnvironmentReading] = Field(default_factory=list)
    report_time: str = "08:00"
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_source_connection(self) -> "MonitoringProfileRequest":
        if isinstance(self.source_reference, str) and not self.source_reference.strip():
            raise ValueError("source_reference cannot be empty when provided.")
        has_reference = self.source_reference is not None
        has_type = self.source_type is not None
        if has_reference != has_type:
            raise ValueError(
                "source_reference and source_type must be provided together or both omitted."
            )
        if self.source_type == MonitoringSourceType.WEBCAM and (
            not isinstance(self.source_reference, int) or isinstance(self.source_reference, bool)
        ):
            raise ValueError("webcam source_reference must be an integer camera index.")
        return self


class MonitoringSourceRequest(BaseModel):
    """A deliberate source connection; it never changes the animal's other settings."""

    source_reference: str | int
    source_type: MonitoringSourceType

    @model_validator(mode="after")
    def validate_webcam_reference(self) -> "MonitoringSourceRequest":
        if self.source_type == MonitoringSourceType.WEBCAM and (
            not isinstance(self.source_reference, int) or isinstance(self.source_reference, bool)
        ):
            raise ValueError("webcam source_reference must be an integer camera index.")
        if isinstance(self.source_reference, str) and not self.source_reference.strip():
            raise ValueError("source_reference cannot be empty.")
        return self


class MonitoringLocationRequest(BaseModel):
    """Explicit owner-supplied location; coordinates are never inferred."""

    location_name: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_location(self) -> "MonitoringLocationRequest":
        self.location_name = self.location_name.strip() if self.location_name else None
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together or both omitted.")
        return self


class CameraPreviewRequest(BaseModel):
    """Narrow local-only camera preview input; paths and arbitrary media are not accepted."""

    camera_index: StrictInt = Field(ge=0, le=32)


class NextWindowRequest(BaseModel):
    window_max_samples: int = Field(default=2, ge=1, le=10)


class OwnerUpdateRequest(BaseModel):
    """Confirmed typed or voice owner context; draft creation never persists it."""

    category: OwnerUpdateCategory
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)
    reading: DirectEnvironmentReading | None = None
    input_method: Literal["typed", "voice"] = "typed"

    @model_validator(mode="after")
    def validate_update_shape(self) -> "OwnerUpdateRequest":
        note = self.note.strip() if self.note else None
        if self.category == OwnerUpdateCategory.MEASUREMENT:
            if self.reading is None:
                raise ValueError("measurement updates require a direct reading.")
            return self
        if self.reading is not None:
            raise ValueError("only measurement updates may include a direct reading.")
        if not note:
            raise ValueError("non-measurement updates require a non-empty note.")
        self.note = note
        return self


def _workflow_http_error(error: Exception) -> HTTPException:
    """Return actionable but non-sensitive workflow failures to API callers."""
    logger.warning("Comfort-z workflow request failed: %s", type(error).__name__)
    if isinstance(error, MonitoringProfileNotFoundError):
        return HTTPException(status_code=404, detail="Animal profile was not found.")
    if isinstance(error, MonitoringSourceNotConnectedError):
        return HTTPException(status_code=409, detail="Monitoring source is not connected.")
    if isinstance(error, CameraCaptureError):
        return HTTPException(status_code=503, detail="Camera preview is unavailable. Check the local camera and try again.")
    if isinstance(error, MediaStorageError):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, VoiceUpdateError):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, VoiceUpdateUnavailableError):
        return HTTPException(status_code=503, detail="Voice updates are temporarily unavailable. You can add an update manually.")
    if isinstance(error, TemperatureUnitConfirmationRequired):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, (ValueError, FileNotFoundError)):
        return HTTPException(status_code=400, detail="Invalid monitoring input.")
    if isinstance(error, ObservationRepositoryError):
        return HTTPException(status_code=503, detail="Observation storage is unavailable.")
    return HTTPException(status_code=502, detail="Monitoring analysis is temporarily unavailable.")


def _profile_payload(profile: MonitoringProfile | dict) -> dict:
    """Return profile data with a safe photo URL instead of an app filesystem path."""
    if isinstance(profile, dict):
        payload = dict(profile)
    else:
        payload = profile.model_dump(mode="json")
    reference = payload.get("profile_photo_reference")
    if isinstance(reference, str):
        try:
            store = get_local_media_store()
            store.resolve(reference)
            payload["profile_photo_url"] = store.public_url(reference)
        except MediaStorageError:
            payload["profile_photo_url"] = None
    return payload


def _require_existing_profile(animal_id: str) -> MonitoringProfile:
    profile = get_monitoring_state_repository().get_profile(animal_id)
    if profile is None:
        raise MonitoringProfileNotFoundError(f"No monitoring profile exists for animal {animal_id!r}.")
    return profile


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the single-page application frontend shell if present."""
    index_path = STATIC_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return HTMLResponse(
        "<!DOCTYPE html><html><head><title>Comfort-z</title></head>"
        "<body><h1>Comfort-z</h1><p>Frontend is initializing.</p></body></html>"
    )


@app.get("/demo-video/{filename}")
async def demo_video(filename: str):
    """Safely serve local demonstration videos if present, without failing if absent."""
    safe_filename = Path(filename).name
    video_path = DEMO_VIDEOS_DIR / safe_filename
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Demo video not available.")
    return FileResponse(video_path, media_type="video/mp4")


@app.get("/animals")
async def list_animals() -> list[dict]:
    """Return all saved monitoring profiles."""
    try:
        profiles = await run_in_threadpool(
            lambda: get_monitoring_state_repository().list_profiles()
        )
    except Exception as error:
        raise _workflow_http_error(error) from error
    return [_profile_payload(profile) for profile in profiles]


@app.get("/health")
def health() -> dict[str, str]:
    """Lightweight Cloud Run health check with no Gemini or Firestore request."""
    return {
        "status": "ok",
        "agent": root_agent.name,
        "model": str(root_agent.model),
        "observation_store": os.getenv("OBSERVATION_STORE", "local").lower(),
    }


@app.get("/media/{media_kind}/{filename}")
async def serve_owner_media(media_kind: str, filename: str):
    """Serve one generated local/demo media object without exposing directories."""
    try:
        reference = f"{media_kind}/{filename}"
        path = get_local_media_store().resolve(reference)
    except MediaStorageError as error:
        logger.warning("Requested owner media was unavailable: %s", type(error).__name__)
        raise HTTPException(status_code=404, detail="Media not available.") from error
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, no-store"})


@app.post("/monitor")
async def monitor(request: MonitorRequest) -> dict:
    """Invoke the existing stateful ADK monitoring tool for one visual input."""
    try:
        return await run_in_threadpool(monitor_animal, **request.model_dump())
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.get("/animals/{animal_id}/observations")
async def recent_observations(
    animal_id: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> list[dict]:
    """Expose the existing repository-backed history tool without duplicating it."""
    try:
        return await run_in_threadpool(get_recent_observations, animal_id, limit)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/animals/{animal_id}/owner-updates")
async def create_owner_update(animal_id: str, request: OwnerUpdateRequest) -> dict:
    """Save owner-provided care context without invoking monitoring or Gemini."""
    try:
        return await run_in_threadpool(
            record_owner_update,
            animal_id,
            request.category.value,
            request.occurred_at,
            request.note,
            request.reading,
            request.input_method,
        )
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post(
    "/animals/{animal_id}/owner-update-drafts/voice",
    response_model=VoiceOwnerUpdateDraftResponse,
)
async def create_voice_owner_update_draft_batch(
    animal_id: str,
    audio: UploadFile = File(...),
    capture_timestamp: datetime = Form(...),
    capture_duration_ms: int = Form(...),
    browser_timezone: str | None = Form(default=None),
    locale: str | None = Form(default=None),
) -> VoiceOwnerUpdateDraftResponse:
    """Transcribe and normalize one short recording without persisting care updates."""
    try:
        audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
        return await run_in_threadpool(
            create_voice_owner_update_drafts,
            animal_id,
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "",
            capture_timestamp=capture_timestamp,
            capture_duration_ms=capture_duration_ms,
            browser_timezone=browser_timezone,
            locale=locale,
        )
    except Exception as error:
        raise _workflow_http_error(error) from error
    finally:
        await audio.close()


@app.get("/animals/{animal_id}/owner-updates")
async def recent_owner_updates(
    animal_id: str,
    limit: int = Query(default=20, ge=1, le=50),
) -> list[dict]:
    """Return owner-provided context separately from Gemini observation history."""
    try:
        return await run_in_threadpool(get_recent_owner_updates, animal_id, limit)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/monitoring/profiles")
async def save_monitoring_profile(request: MonitoringProfileRequest) -> dict:
    """Save the owner goal and bounded source configuration; it starts no background loop."""
    try:
        saved = await run_in_threadpool(create_monitoring_profile, **request.model_dump())
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.get("/monitoring/{animal_id}/profile")
async def get_monitoring_profile(animal_id: str) -> dict:
    try:
        profile = await run_in_threadpool(
            lambda: get_monitoring_state_repository().get_profile(animal_id)
        )
    except Exception as error:
        raise _workflow_http_error(error) from error
    if profile is None:
        raise HTTPException(status_code=404, detail="Monitoring profile was not found.")
    return _profile_payload(profile)


@app.put("/monitoring/{animal_id}/location")
async def update_monitoring_location(animal_id: str, request: MonitoringLocationRequest) -> dict:
    """Update only owner-provided location context; monitoring state is preserved."""
    try:
        saved = await run_in_threadpool(
            set_profile_location,
            animal_id,
            request.location_name,
            request.latitude,
            request.longitude,
        )
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/animals/{animal_id}/profile-photo")
async def upload_profile_photo(animal_id: str, photo: UploadFile = File(...)) -> dict:
    """Store one bounded decorative image without changing monitoring state."""
    try:
        await run_in_threadpool(_require_existing_profile, animal_id)
        content = await photo.read(MAX_PROFILE_PHOTO_BYTES + 1)
        stored = get_local_media_store().save_profile_photo(
            content, content_type=photo.content_type or "", original_name=photo.filename
        )
        try:
            saved = await run_in_threadpool(set_profile_photo_reference, animal_id, stored.reference)
        except Exception:
            get_local_media_store().remove(stored.reference)
            raise
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error
    finally:
        await photo.close()


@app.post("/monitoring/{animal_id}/video-source")
async def upload_monitoring_video(animal_id: str, video: UploadFile = File(...)) -> dict:
    """Upload one local/demo video and connect it as the profile's single paused source."""
    try:
        await run_in_threadpool(_require_existing_profile, animal_id)
        content = await video.read(MAX_VIDEO_UPLOAD_BYTES + 1)
        stored = get_local_media_store().save_video(
            content, content_type=video.content_type or "", original_name=video.filename
        )
        try:
            saved = await run_in_threadpool(
                connect_monitoring_source,
                animal_id,
                stored.reference,
                MonitoringSourceType.VIDEO.value,
                stored.display_name,
            )
        except Exception:
            get_local_media_store().remove(stored.reference)
            raise
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error
    finally:
        await video.close()


@app.put("/monitoring/{animal_id}/source")
async def set_monitoring_source(animal_id: str, request: MonitoringSourceRequest) -> dict:
    """Connect or change one source and leave it paused until the owner starts it."""
    try:
        saved = await run_in_threadpool(
            connect_monitoring_source,
            animal_id,
            request.source_reference,
            request.source_type.value,
        )
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.delete("/monitoring/{animal_id}/source")
async def remove_monitoring_source(animal_id: str) -> dict:
    """Disconnect a source without deleting the animal profile or its history."""
    try:
        saved = await run_in_threadpool(disconnect_monitoring_source, animal_id)
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/monitoring/camera-preview")
async def preview_local_camera(request: CameraPreviewRequest) -> Response:
    """Return one local JPEG snapshot without saving, analyzing, or scheduling anything."""
    try:
        jpeg = await run_in_threadpool(capture_local_camera_preview, request.camera_index)
        if not is_usable_jpeg_bytes(jpeg):
            raise CameraCaptureError("Camera preview did not produce a valid JPEG.")
    except Exception as error:
        raise _workflow_http_error(error) from error
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/monitoring/{animal_id}/start")
async def start_monitoring_profile(animal_id: str) -> dict:
    try:
        saved = await run_in_threadpool(start_monitoring, animal_id)
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/monitoring/{animal_id}/pause")
async def pause_monitoring_profile(animal_id: str) -> dict:
    try:
        saved = await run_in_threadpool(pause_monitoring, animal_id)
        return _profile_payload(saved)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/monitoring/{animal_id}/next-window")
async def run_next_monitoring_window(
    animal_id: str, request: NextWindowRequest = NextWindowRequest()
) -> dict:
    """Cloud Scheduler can invoke this bounded operation in a future deployment."""
    try:
        return await run_in_threadpool(
            monitor_next_window, animal_id, window_max_samples=request.window_max_samples
        )
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.post("/monitoring/{animal_id}/daily-report")
async def run_daily_monitoring_report(animal_id: str) -> dict:
    try:
        return await run_in_threadpool(generate_daily_report, animal_id)
    except Exception as error:
        raise _workflow_http_error(error) from error


@app.get("/animals/{animal_id}/reports")
async def recent_daily_reports(
    animal_id: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> list[dict]:
    try:
        return await run_in_threadpool(get_recent_daily_reports, animal_id, limit)
    except Exception as error:
        raise _workflow_http_error(error) from error
