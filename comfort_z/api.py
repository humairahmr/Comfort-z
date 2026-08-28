"""Minimal Cloud Run HTTP adapter for the existing Comfort-z ADK tools."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from comfort_z.agent import root_agent
from comfort_z.services.repository import ObservationRepositoryError
from comfort_z.tools.monitoring import get_recent_observations, monitor_animal

logger = logging.getLogger(__name__)

app = FastAPI(title="Comfort-z", version="0.1.0")


class MonitorRequest(BaseModel):
    """Inputs passed unchanged to Comfort-z's existing monitor_animal tool."""

    animal_id: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    source_info: str | None = None
    animal_name: str | None = None
    expected_species: str | None = None


def _workflow_http_error(error: Exception) -> HTTPException:
    """Return actionable but non-sensitive workflow failures to API callers."""
    logger.warning("Comfort-z workflow request failed: %s", type(error).__name__)
    if isinstance(error, (ValueError, FileNotFoundError)):
        return HTTPException(status_code=400, detail="Invalid monitoring input.")
    if isinstance(error, ObservationRepositoryError):
        return HTTPException(status_code=503, detail="Observation storage is unavailable.")
    return HTTPException(status_code=502, detail="Monitoring analysis is temporarily unavailable.")


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
