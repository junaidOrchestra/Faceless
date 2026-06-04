"""Public API schemas for the orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoStatus = Literal["queued", "running", "done", "failed"]


class VideoCredentials(BaseModel):
    """Passed through to the CLIP server in memory only."""

    pexels: str | None = None


class CreateVideoResponse(BaseModel):
    video_job_id: str = Field(..., examples=["vid-abc"])


class VideoStatusResponse(BaseModel):
    video_job_id: str
    status: VideoStatus
    progress: str | None = None
    result_url: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ErrorResponse(BaseModel):
    detail: str
