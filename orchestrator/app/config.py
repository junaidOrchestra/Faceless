"""Typed configuration for the orchestrator service."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings are read from the environment (see ``.env.example``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    api_auth_secret: str
    log_level: str = "INFO"

    clip_server_url: str = Field(default="http://localhost:7860")
    clip_server_secret: str

    llm_provider: Literal["gemini", "cerebras", "local", "stub"] = "cerebras"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    cerebras_api_key: str | None = None
    cerebras_model: str = "gpt-oss-120b"
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    local_llm_model_path: str | None = None

    # --- LLM generation + resilience (provider-agnostic) ---------------------
    llm_max_tokens: int = Field(
        default=8192,
        description="Max completion tokens (includes reasoning tokens for gpt-oss).",
    )
    llm_reasoning_effort: str = Field(
        default="low",
        description="gpt-oss reasoning effort: low | medium | high.",
    )
    llm_request_timeout_s: float = Field(
        default=60.0, description="Per-request timeout for LLM calls."
    )
    llm_max_retries: int = Field(
        default=0,
        description="Retries on timeout/connection errors. 0 = retry indefinitely.",
    )
    llm_retry_backoff_s: float = Field(
        default=2.0, description="Initial backoff between LLM retries."
    )
    llm_retry_backoff_max_s: float = Field(
        default=30.0, description="Cap on exponential backoff between LLM retries."
    )
    llm_chunk_size: int = Field(
        default=18,
        description=(
            "Beats per batched visual-director call. Smaller chunks keep the JSON "
            "output well within max_tokens (gpt-oss reasoning shares the budget)."
        ),
    )

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Job queue / worker pool ---------------------------------------------
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL used as the video-job dispatch queue.",
    )
    # Per-stage worker pool sizes. The pipeline is split into independent stages
    # (transcribe -> llm -> clip poll -> render) each fed by its own Redis queue,
    # so they scale separately. Keep modest on a small box (each render runs
    # ffmpeg; each transcribe runs whisper).
    transcribe_concurrency: int = Field(default=2, description="Parallel transcribe workers.")
    llm_concurrency: int = Field(default=2, description="Parallel LLM+clip-submit workers.")
    render_concurrency: int = Field(default=2, description="Parallel ffmpeg render workers.")

    worker_poll_interval_s: float = 1.0
    job_running_timeout_s: float = 900.0
    clip_poll_interval_s: float = 2.0
    clip_poll_timeout_s: float = 300.0
    # Upper bound on items (beat × keyword queries) sent to the clip-server in a
    # single job. Must stay <= the clip-server's max_items_per_job. The LLM stage
    # reduces keywords-per-beat for very long narrations so this is never blown.
    clip_max_items_per_job: int = Field(
        default=512,
        description="Cap on total clip-search items; keep <= clip-server max_items_per_job.",
    )

    clip_poll_scan_interval_s: float = Field(
        default=2.0,
        description="How often the single clip poller scans awaiting_clip jobs.",
    )
    clip_poll_max_age_s: float = Field(
        default=600.0,
        description="Fail an awaiting_clip job whose clip search never finishes in this long.",
    )

    max_upload_bytes: int = 50 * 1024 * 1024
    render_temp_dir: str = "/tmp/faceless-render"

    # --- FFmpeg render tuning -------------------------------------------------
    # Within a single render job, segments (download + encode) run in a thread
    # pool instead of one-at-a-time. Total ffmpeg processes on the box is roughly
    # render_concurrency * render_segment_concurrency, each capped to
    # render_threads, so keep the product sane for the host's core count.
    render_segment_concurrency: int = Field(
        default=4,
        description="Parallel segment (download+encode) tasks within one render job.",
    )
    render_threads: int = Field(
        default=2,
        description="ffmpeg -threads per segment encode (bounds CPU oversubscription).",
    )
    # libx264 quality/speed. A faster preset trades file size (not visual
    # quality) for speed at a fixed CRF; lower CRF = higher quality.
    render_preset: str = Field(
        default="veryfast",
        description="libx264 -preset for segment encodes (ultrafast..veryslow).",
    )
    render_crf: int = Field(
        default=20,
        description="libx264 -crf quality (lower is higher quality / larger file).",
    )
    result_base_url: str = Field(
        default="file:///tmp/faceless-results",
        description="Prefix used for the local result_url when storage_local is true.",
    )

    # --- Result storage backend ----------------------------------------------
    storage_local: bool = Field(
        default=True,
        description=(
            "When true (default), keep the rendered mp4 on local disk and return "
            "a local result_url built from result_base_url. When false, upload "
            "the mp4 to Backblaze B2 and return its download URL (requires the "
            "b2_* settings below)."
        ),
    )
    b2_key_id: str | None = Field(
        default=None, description="Backblaze B2 application key id (keyID)."
    )
    b2_application_key: str | None = Field(
        default=None, description="Backblaze B2 application key (secret)."
    )
    b2_bucket_name: str | None = Field(
        default=None, description="Backblaze B2 bucket to upload results into."
    )
    b2_prefix: str = Field(
        default="",
        description="Optional key prefix (folder) inside the bucket, e.g. 'videos'.",
    )
    b2_public_base_url: str | None = Field(
        default=None,
        description=(
            "Optional public base URL (custom domain / CDN) for B2 files. If set, "
            "result_url = <base>/<key>; otherwise the bucket's native download URL "
            "is used. Only meaningful for public buckets."
        ),
    )

    default_sources: list[str] = Field(default_factory=lambda: ["stub"])
    default_user_id: str = "anonymous"

    max_fallback_ratio: float = Field(
        default=0.5,
        description=(
            "Fail a job when the fraction of beats that fell back to generated "
            "text cards exceeds this. Guards against shipping a mostly text-only "
            "video when no media source returned results. "
            "Set to 1.0 to disable."
        ),
    )

    # --- Transcription / beat segmentation -----------------------------------
    whisper_model_size: str = Field(
        default="base", description="faster-whisper model size (tiny/base/small/...)."
    )
    # Rule-based re-chunking of Whisper word timestamps into visual beats.
    beat_min_duration_s: float = Field(
        default=1.5,
        description="Beats shorter than this are merged with a neighbor (avoid flashes).",
    )
    beat_target_duration_s: float = Field(
        default=3.5,
        description="Preferred on-screen beat length used to bias splits/merges.",
    )
    beat_max_duration_s: float = Field(
        default=5.0,
        description="Beats longer than this are split at the best internal break.",
    )
    beat_pause_threshold_s: float = Field(
        default=0.35,
        description="Silence gap between words treated as a natural cut point.",
    )
    beat_normalize_transcript: bool = Field(
        default=False,
        description="Config gate for optional ASR cleanup before segmentation (no-op for now).",
    )
    beat_use_external_segmenter: bool = Field(
        default=True,
        description="Prefer pysbd for sentence splitting; fall back to stdlib if absent.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
