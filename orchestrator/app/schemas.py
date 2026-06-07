"""Public API schemas for the orchestrator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoStatus = Literal[
    "queued",  # awaiting transcription
    "transcribing",
    "transcribed",  # awaiting LLM
    "llm",
    "awaiting_clip",  # clip search in flight (poller watching)
    "ready",  # prepared; call POST /render to produce the MP4
    "render_queued",
    "rendering",
    "done",
    "failed",
]


class VideoCredentials(BaseModel):
    """Passed through to the CLIP server in memory only."""

    pexels: str | None = None
    pixabay: str | None = None


class CreateVideoResponse(BaseModel):
    video_job_id: str = Field(..., examples=["vid-abc"])


class VideoStatusResponse(BaseModel):
    video_job_id: str
    status: VideoStatus
    progress: str | None = None
    result_url: str | None = None
    error: str | None = None


class BeatAssignmentOut(BaseModel):
    """The clip selected for a beat. ``platform='generated'`` means a text fallback."""

    platform: str | None = None
    media_url: str | None = None
    preview_url: str | None = None
    kind: str | None = None
    score: float | None = None
    attribution: str | None = None


class BeatCandidateOut(BaseModel):
    """One ranked option for a beat (the default plus alternates the user can pick)."""

    platform: str | None = None
    kind: str | None = None
    media_url: str | None = None
    preview_url: str | None = None
    score: float | None = None
    attribution: str | None = None
    selected: bool = False


class BeatOut(BaseModel):
    """One beat: transcript text, on-screen timing, queries, and clip choices."""

    index: int
    text: str
    start_s: float
    end_s: float
    queries: dict | None = None
    assignment: BeatAssignmentOut | None = None
    # Up to 3 options (selected first, then alternates), each with preview + media URL.
    candidates: list[BeatCandidateOut] = Field(default_factory=list)


class BeatsResponse(BaseModel):
    video_job_id: str
    beats: list[BeatOut] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ErrorResponse(BaseModel):
    detail: str
