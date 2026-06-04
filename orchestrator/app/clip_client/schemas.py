"""Loose duplicate of CLIP server job API models (network boundary — not shared package)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "done", "failed"]


class ClipJobItemInput(BaseModel):
    ref: str
    keyword: str
    sources: list[str] | None = None


class ClipJobCredentials(BaseModel):
    pexels: str | None = None


class ClipJobOptions(BaseModel):
    orientation: str | None = None
    per_page: int | None = None
    min_score: float | None = None


class ClipCreateJobRequest(BaseModel):
    job_id: str
    items: list[ClipJobItemInput]
    credentials: ClipJobCredentials = Field(default_factory=ClipJobCredentials)
    options: ClipJobOptions = Field(default_factory=ClipJobOptions)


class ClipRankedAsset(BaseModel):
    platform: str
    kind: str
    media_url: str
    preview_url: str
    attribution_name: str | None = None
    attribution_url: str | None = None
    license: str | None = None
    duration: float | None = None
    score: float


class ClipJobItemResult(BaseModel):
    ref: str
    assets: list[ClipRankedAsset] = Field(default_factory=list)
    error: str | None = None


class ClipJobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    items: list[ClipJobItemResult] = Field(default_factory=list)
    error: str | None = None
