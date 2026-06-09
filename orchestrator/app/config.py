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
    # Legacy static bearer (pre-Supabase). Unused for end-user routes; kept so
    # existing deploy envs don't break on upgrade. User auth is Supabase JWT.
    api_auth_secret: str | None = Field(default=None)
    log_level: str = "INFO"

    # --- Identity / Supabase Auth (verification only) ------------------------
    # The orchestrator authenticates end users by verifying the Supabase access
    # token (a JWT) on every request — see app.identity. Supabase's default
    # signing is HS256 with the project JWT secret; newer projects may use
    # asymmetric keys, in which case the JWKS endpoint is used instead. The
    # identity layer is deliberately thin so it can be swapped without touching
    # project/credit logic.
    supabase_url: str | None = Field(
        default=None,
        description="Supabase project URL, e.g. https://<ref>.supabase.co (used to derive JWKS).",
    )
    supabase_jwt_secret: str | None = Field(
        default=None,
        description="Supabase JWT secret for HS256 verification (Dashboard → API → JWT secret).",
    )
    supabase_jwt_audience: str = Field(
        default="authenticated",
        description="Expected JWT 'aud' claim for authenticated Supabase users.",
    )
    supabase_jwks_url: str | None = Field(
        default=None,
        description=(
            "Override for the JWKS endpoint used when the project signs tokens with "
            "asymmetric keys. Defaults to <SUPABASE_URL>/auth/v1/.well-known/jwks.json."
        ),
    )

    # --- Rate limiting (Redis token buckets) ---------------------------------
    rate_limit_enabled: bool = Field(
        default=True, description="Master switch for Redis-backed per-user/IP rate limits."
    )
    rate_limit_create_per_min: int = Field(
        default=10,
        description="Max POST /videos (create + upload) requests per user per minute.",
    )
    rate_limit_render_per_min: int = Field(
        default=20,
        description="Max POST /videos/{id}/render requests per user per minute.",
    )

    # --- Database connection pool --------------------------------------------
    # Bound the pool so concurrency (stage workers each hold a session for the
    # duration of a stage, plus heartbeat/sweeper/poller/API sessions) can never
    # open unbounded connections or wait forever for one. Keep
    # ``db_pool_size + db_max_overflow`` >= the sum of stage concurrencies plus a
    # little headroom, and within the database's max_connections.
    db_pool_size: int = Field(default=10, description="Persistent pooled DB connections.")
    db_max_overflow: int = Field(
        default=5, description="Extra connections allowed beyond db_pool_size under load."
    )
    db_pool_timeout_s: float = Field(
        default=30.0, description="How long to wait for a free pooled connection before erroring."
    )
    db_pool_recycle_s: float = Field(
        default=1800.0, description="Recycle connections older than this (avoids stale server cuts)."
    )
    db_statement_timeout_s: float = Field(
        default=30.0,
        description=(
            "Postgres statement_timeout for every connection (0 disables). DB ops "
            "here are small, so this kills a stuck/slow query without affecting the "
            "long CPU work (whisper/ffmpeg/LLM) that runs outside transactions."
        ),
    )
    db_lock_timeout_s: float = Field(
        default=10.0,
        description="Postgres lock_timeout for every connection (0 disables).",
    )
    db_force_ipv4: bool = Field(
        default=True,
        description=(
            "Resolve the database host to IPv4 and connect via libpq 'hostaddr' "
            "(host is kept for TLS/SNI). Works around hosts (e.g. Hugging Face "
            "Spaces) with no IPv6 route connecting to dual-stack providers like "
            "Neon, where the resolver prefers an unreachable AAAA address. Set "
            "false to use the OS resolver as-is."
        ),
    )

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
        default=5,
        description=(
            "Retries on timeout/connection errors before failing. 0 = retry "
            "indefinitely (the LLM stage deadline still bounds it as a backstop)."
        ),
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
    job_heartbeat_interval_s: float = Field(
        default=15.0,
        description="How often an active worker refreshes video_jobs.heartbeat_at.",
    )
    job_stale_timeout_s: float = Field(
        default=120.0,
        description=(
            "How old heartbeat_at can get before an active job is treated as "
            "orphaned and requeued or failed."
        ),
    )
    job_stale_sweep_interval_s: float = Field(
        default=30.0,
        description="How often the orchestrator scans active jobs for stale heartbeats.",
    )
    job_max_attempts: int = Field(
        default=3,
        description="Maximum active-stage attempts before a stale job is marked failed.",
    )
    # --- Per-stage execution deadlines (backstops) ---------------------------
    # Each worker stage is wrapped in asyncio.wait_for(<timeout>). A stage that
    # exceeds its deadline (hung LLM/whisper/ffmpeg/B2) is abandoned and the job
    # is marked failed instead of pinning a worker forever. These are generous
    # ceilings: legitimate jobs finish well under them, so only pathological
    # hangs are caught. Note: wait_for cancels the *await* but cannot kill an
    # underlying thread (whisper/B2) — the real hard kill for ffmpeg is
    # ``render_subprocess_timeout_s`` below.
    transcribe_timeout_s: float = Field(
        default=900.0, description="Max wall-clock for the transcribe stage before failing the job."
    )
    llm_stage_timeout_s: float = Field(
        default=600.0,
        description=(
            "Max wall-clock for the LLM + clip-submit stage. Also bounds the "
            "Cerebras retry loop even if llm_max_retries is 0."
        ),
    )
    render_stage_timeout_s: float = Field(
        default=1800.0, description="Max wall-clock for the render stage before failing the job."
    )
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

    # --- Uploaded media validation -------------------------------------------
    # Beyond the content-type allow-list, every uploaded/downloaded file is sniffed
    # by magic bytes and decode-probed with ffprobe before it is stored or handed
    # to whisper/ffmpeg, so a disguised payload (e.g. an executable renamed .mp4)
    # or a corrupt/truncated file is rejected up front.
    media_probe_timeout_s: float = Field(
        default=30.0,
        description="Hard timeout for the ffprobe validation of an uploaded/downloaded media file.",
    )
    media_require_audio_stream: bool = Field(
        default=True,
        description="Reject media with no audio track (narration is transcribed from it).",
    )

    # --- FFmpeg render tuning -------------------------------------------------
    # Within a single render job, segments (download + encode) run in a thread
    # pool instead of one-at-a-time. Total ffmpeg processes on the box is roughly
    # render_concurrency * render_segment_concurrency, each capped to
    # render_threads, so keep the product sane for the host's core count.
    render_segment_concurrency: int = Field(
        default=8,
        description="Parallel ffmpeg segment ENCODES within one render job (CPU-bound).",
    )
    render_download_concurrency: int = Field(
        default=8,
        description=(
            "Parallel asset downloads within one render job (network-bound; runs "
            "in its own pool so downloads overlap encodes and aren't capped by the "
            "CPU-bound encode concurrency)."
        ),
    )
    render_threads: int = Field(
        default=2,
        description="ffmpeg -threads per segment encode (bounds CPU oversubscription).",
    )
    render_subprocess_timeout_s: float = Field(
        default=300.0,
        description=(
            "Hard timeout for a single ffmpeg invocation (one segment encode / "
            "concat / mux). On expiry the process is killed and the render fails, "
            "so a wedged ffmpeg can never pin a render worker or CPU forever."
        ),
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
    b2_timeout_s: float = Field(
        default=300.0,
        description=(
            "Backstop wall-clock for a single B2 operation (upload/download/"
            "presign). b2sdk retries internally and can stall for minutes on an "
            "outage; this makes submit/render/download fail predictably instead "
            "of hanging. (The worker thread may keep running until the SDK gives "
            "up, but the job no longer blocks on it.)"
        ),
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
    # Per-beat source overrides for the visual director's editorial classes. These
    # beats want authentic photographs of a real subject, not generic stock, so
    # they route to Openverse (free, keyless, aggregates CC/GLAM/Flickr-CC) with
    # Pexels as a fallback. Flickr is intentionally NOT a default (it is not free);
    # swap "openverse" -> "flickr" here later to switch providers. Beats that are
    # neither person nor event keep using ``default_sources`` (Pexels).
    person_sources: list[str] = Field(
        default_factory=lambda: ["openverse", "pexels_video"],
        description=(
            "Source override for 'person' beats (a real, named individual). "
            "Options include openverse, pexels_video, flickr, wikimedia."
        ),
    )
    event_sources: list[str] = Field(
        default_factory=lambda: ["openverse", "pexels_video"],
        description=(
            "Source override for 'event' beats (a specific historical event). "
            "Options include openverse, pexels_video, flickr, wikimedia."
        ),
    )
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
