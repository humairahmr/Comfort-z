"""Minimal Cloud Run HTTP adapter for the existing Comfort-z ADK tools."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from comfort_z.agent import root_agent
from comfort_z.models import DirectEnvironmentReading, MonitoringProfile, MonitoringSourceType
from comfort_z.services.repository import ObservationRepositoryError, get_monitoring_state_repository
from comfort_z.services.orchestration import MonitoringSourceNotConnectedError
from comfort_z.tools.monitoring import (
    create_monitoring_profile,
    generate_daily_report,
    get_recent_daily_reports,
    get_recent_observations,
    monitor_animal,
    monitor_next_window,
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
        return self


class NextWindowRequest(BaseModel):
    window_max_samples: int = Field(default=2, ge=1, le=10)


def _workflow_http_error(error: Exception) -> HTTPException:
    """Return actionable but non-sensitive workflow failures to API callers."""
    logger.warning("Comfort-z workflow request failed: %s", type(error).__name__)
    if isinstance(error, MonitoringSourceNotConnectedError):
        return HTTPException(status_code=409, detail="Monitoring source is not connected.")
    if isinstance(error, (ValueError, FileNotFoundError)):
        return HTTPException(status_code=400, detail="Invalid monitoring input.")
    if isinstance(error, ObservationRepositoryError):
        return HTTPException(status_code=503, detail="Observation storage is unavailable.")
    return HTTPException(status_code=502, detail="Monitoring analysis is temporarily unavailable.")


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
    return [profile.model_dump(mode="json") for profile in profiles]


@app.get("/health")
def health() -> dict[str, str]:
    """Lightweight Cloud Run health check with no Gemini or Firestore request."""
    return {
        "status": "ok",
        "agent": root_agent.name,
        "model": str(root_agent.model),
        "observation_store": os.getenv("OBSERVATION_STORE", "local").lower(),
    }


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


@app.post("/monitoring/profiles")
async def save_monitoring_profile(request: MonitoringProfileRequest) -> dict:
    """Save the owner goal and bounded source configuration; it starts no background loop."""
    try:
        return await run_in_threadpool(create_monitoring_profile, **request.model_dump())
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
    return profile.model_dump(mode="json")


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
