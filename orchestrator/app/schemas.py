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
    flickr: str | None = None


class CreateVideoResponse(BaseModel):
    video_job_id: str = Field(..., examples=["vid-abc"])


class ThemeChoice(BaseModel):
    """Content theme: match the script, or fill every beat from a chosen vibe.

    ``mode='script'`` (default) keeps the transcript-driven visual search.
    ``mode='vibe'`` ignores the transcript for visuals and instead searches for
    keywords belonging to ``vibe`` (e.g. 'space', 'forest'); ``vibe`` must be one
    of the known slugs in :mod:`app.vibes`.
    """

    mode: Literal["script", "vibe"] = "script"
    vibe: str | None = Field(
        default=None,
        examples=["space", "forest", "ocean"],
        description="Vibe slug (required when mode='vibe'). See app/vibes.py.",
    )


class PrepareRequest(BaseModel):
    """Output choices supplied after transcription to start the clip search.

    When a job is submitted without a ``format`` it pauses at ``transcribed``
    (beats are ready to review). This request supplies the output shape — which
    drives the orientation/quality of the stock media fetched — and unblocks the
    LLM + clip-search stage. ``subtitles`` is recorded for the later render.
    """

    format: str | None = Field(
        default=None,
        examples=["9:16", "16:9", "1:1", "youtube_shorts"],
        description="Output format/aspect (same values as POST /videos 'format').",
    )
    quality: str | None = Field(
        default=None, description="Downloaded media tier: 'sd' | 'hd' | 'max'."
    )
    subtitles: bool = Field(
        default=False, description="Burn per-beat narration captions at render time."
    )
    theme: ThemeChoice | None = Field(
        default=None,
        description=(
            "Content theme. Omit (or mode='script') to match the transcript; "
            "mode='vibe' fills every beat from the chosen vibe instead."
        ),
    )


class RenderRequest(BaseModel):
    """Optional final-output choices applied just before rendering.

    ``overrides`` maps a beat index to the index of the candidate (within that
    beat's stored ``candidates`` list) the user picked in the editor. Only beats
    whose choice differs from the stored default need to be sent.

    ``format`` / ``subtitles`` let the editor change the output shape and caption
    toggle at render time (e.g. the user switched 9:16 -> 16:9 on the Pick Clips
    screen after the clip search already ran). When omitted, the values stored at
    /prepare are kept. NOTE: the orientation of the *stock media* was chosen at
    clip-search time from the prepared format; changing ``format`` here only
    changes the encoded output dimensions (the renderer cover-scales/crops), not
    which clips were fetched.

    Applying these is idempotent — re-rendering with the same values yields the
    same result — so retries from a flaky client are safe. Out-of-range or
    unknown beats are ignored rather than failing the render.
    """

    overrides: dict[int, int] = Field(
        default_factory=dict,
        examples=[{"3": 1, "7": 2}],
        description="beat_index -> candidate_index (position in the beat's candidates).",
    )
    format: str | None = Field(
        default=None,
        examples=["9:16", "16:9", "1:1", "youtube_shorts"],
        description="Override the output format/aspect (same values as POST /videos 'format').",
    )
    subtitles: bool | None = Field(
        default=None,
        description="Override whether per-beat narration captions are burned in.",
    )


class VideoStatusResponse(BaseModel):
    video_job_id: str
    status: VideoStatus
    progress: str | None = None
    result_url: str | None = None
    error: str | None = None
    # The content theme chosen for this job (match the script, or a vibe). Read
    # from the job payload so the editor's pick-clips/render screens can show
    # which theme is in effect. Defaults to script when unset.
    theme: ThemeChoice | None = None


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


class TierInfo(BaseModel):
    """Per-tier limits surfaced to the client (mirrors app.tiers.TierConfig)."""

    name: str
    label: str
    monthly_credits: int
    max_video_seconds: int
    max_resolution_height: int
    watermark: bool
    features: list[str] = Field(default_factory=list)


class MeResponse(BaseModel):
    """The authenticated user's account summary."""

    id: str
    email: str | None = None
    name: str | None = None
    tier: str
    credits: int
    tier_info: TierInfo


class CreditTransactionOut(BaseModel):
    id: int
    delta: int
    reason: str
    project_id: str | None = None
    created_at: str


class CreditsResponse(BaseModel):
    credits: int
    transactions: list[CreditTransactionOut] = Field(default_factory=list)


class ProjectOut(BaseModel):
    id: str
    title: str | None = None
    input_type: str | None = None
    status: str
    # Fine-grained pipeline stage of the underlying job (e.g. "transcribing",
    # "llm_vocabulary", "rendering") so the UI can show *where* a processing
    # project is, and the failure reason when it failed. Both are None when the
    # job row is absent.
    progress: str | None = None
    error: str | None = None
    result_url: str | None = None
    created_at: str
    updated_at: str


class ProjectsResponse(BaseModel):
    projects: list[ProjectOut] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ErrorResponse(BaseModel):
    detail: str
