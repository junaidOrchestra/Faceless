"""Pydantic v2 request/response models for the public HTTP API.

Every route declares a ``response_model`` from this module. Examples are
attached via ``Field(examples=...)`` and ``model_config`` so the generated
OpenAPI at ``/docs`` is self-documenting.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "done", "failed"]
MediaKind = Literal["photo", "video"]


class JobItemInput(BaseModel):
    """One keyword search within a batch job."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"ref": "beat-0", "keyword": "sunrise over mountains", "sources": ["pexels_photo"]}
            ]
        }
    )

    ref: str = Field(
        ...,
        description="Opaque client reference echoed back unchanged (e.g. beat index).",
        examples=["beat-0"],
    )
    keyword: str = Field(..., description="Search phrase to embed and match.", examples=["ocean waves"])
    sources: list[str] | None = Field(
        default=None,
        description="Override enabled sources for this item only.",
        examples=[["pexels_photo", "wikimedia"]],
    )


class JobCredentials(BaseModel):
    """Per-request API keys — used in memory only, never logged or persisted."""

    pexels: str | None = Field(default=None, description="Pexels API key.", examples=["***"])
    pixabay: str | None = Field(default=None, description="Pixabay API key.", examples=["***"])
    flickr: str | None = Field(default=None, description="Flickr API key.", examples=["***"])


class JobOptions(BaseModel):
    """Optional tuning knobs for search and ranking."""

    orientation: str | None = Field(default=None, description="e.g. landscape, portrait, square.")
    quality: str | None = Field(
        default=None,
        description=(
            "Media resolution tier for the downloaded asset: 'sd' (~960px), "
            "'hd' (~1920px, default), or 'max' (largest/original available)."
        ),
        examples=["hd"],
    )
    per_page: int | None = Field(default=None, ge=1, le=80, description="Results per source query.")
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity to include an asset.",
    )
    rank: bool = Field(
        default=True,
        description=(
            "When true (default), download+CLIP-embed each preview and rank by "
            "cosine similarity to the keyword. When false, skip embedding entirely "
            "and return the raw source results (deduped, with durations) — used for "
            "ambient 'vibe' clips that don't need semantic matching."
        ),
    )


class CreateJobRequest(BaseModel):
    """Body for ``POST /jobs``."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "job_id": "orch-clip-abc123",
                    "items": [{"ref": "0", "keyword": "city skyline at night"}],
                    "credentials": {"pexels": "YOUR_KEY"},
                    "options": {"orientation": "landscape", "min_score": 0.25},
                }
            ]
        }
    )

    job_id: str = Field(..., description="Client-supplied id for idempotent resubmits.", examples=["job-1"])
    items: list[JobItemInput] = Field(..., min_length=1)
    credentials: JobCredentials = Field(default_factory=JobCredentials)
    options: JobOptions = Field(default_factory=JobOptions)


class CreateJobResponse(BaseModel):
    """``202`` response after a job is accepted."""

    job_id: str = Field(..., examples=["job-1"])


class RankedAsset(BaseModel):
    """One ranked media asset returned for an item."""

    platform: str
    kind: MediaKind
    media_url: str
    preview_url: str
    attribution_name: str | None = None
    attribution_url: str | None = None
    license: str | None = None
    duration: float | None = None
    score: float = Field(..., description="Cosine similarity between keyword and preview embedding.")


class JobItemResult(BaseModel):
    """Per-item outcome (success or partial failure)."""

    ref: str
    assets: list[RankedAsset] = Field(default_factory=list)
    error: str | None = Field(default=None, description="Set when the item could not be processed.")


class JobStatusResponse(BaseModel):
    """Body for ``GET /jobs/{job_id}``.

    The shape depends on status (the route uses ``response_model_exclude_none`` so
    unset fields are omitted, keeping poll responses tiny):

    * ``queued``/``running`` — only ``job_id`` + ``status`` (no payload, ever).
    * ``failed``             — ``job_id`` + ``status`` + ``error``.
    * ``done``               — ``job_id`` + ``status`` + ``items`` (full result,
      returned only when ALL items are complete — never partial/mid-flight).
    """

    job_id: str
    status: JobStatus
    items: list[JobItemResult] | None = None
    error: str | None = None


class TextEmbedRequest(BaseModel):
    """Body for ``POST /text-embed`` (utility endpoint)."""

    texts: list[str] = Field(..., min_length=1, examples=[["ocean waves", "mountain peak"]])


class TextEmbedResponse(BaseModel):
    """CLIP text embeddings as nested float lists."""

    embeddings: list[list[float]]
    dim: int


class HealthResponse(BaseModel):
    """Liveness probe — no auth required."""

    status: Literal["ok"] = "ok"
    version: str


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    detail: str
