"""Typed application configuration, read from environment variables only.

All runtime configuration flows through :class:`Settings`. No secrets are ever
hard-coded; everything (including the bearer auth secret) comes from the
environment via ``pydantic-settings``. Import :func:`get_settings` to obtain a
process-wide cached instance.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration sourced exclusively from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core service config -------------------------------------------------
    database_url: str = Field(
        ...,
        description="Async SQLAlchemy URL, e.g. postgresql+psycopg://user:pw@host/db",
    )
    api_auth_secret: str = Field(
        ...,
        description="Bearer token required on every route except /health.",
    )
    log_level: str = Field(default="INFO", description="Root log level.")

    # --- Database connection pool --------------------------------------------
    # Bound the pool so item_concurrency (each item opens its own session) plus
    # the worker bookkeeping, sweeper, heartbeat, and API poll sessions can never
    # open unbounded connections or block forever waiting for one. Keep within
    # the database's / pooler's connection limit (Neon pooler in use here).
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
        description="Postgres statement_timeout for every connection (0 disables).",
    )
    db_lock_timeout_s: float = Field(
        default=10.0,
        description="Postgres lock_timeout for every connection (0 disables).",
    )
    db_force_ipv4: bool = Field(
        default=True,
        description=(
            "Pin the DB connection to IPv4 (resolve host's A record, pass as libpq "
            "hostaddr). On by default because this service runs on IPv6-less hosts "
            "(e.g. HF Spaces) talking to dual-stack providers (e.g. Neon) whose "
            "hostname otherwise resolves to an unreachable IPv6 address. Falls back "
            "to the normal resolver when no IPv4 address exists, so it's safe "
            "locally. Set DB_FORCE_IPV4=false to disable."
        ),
    )

    # --- CLIP model ----------------------------------------------------------
    clip_model_name: str = Field(
        default="clip-ViT-B-32",
        description="sentence-transformers CLIP model id (loaded once at startup).",
    )
    clip_device: str = Field(default="cpu", description="Torch device for CLIP.")
    clip_torch_threads: int = Field(
        default=0,
        description=(
            "CPU threads for PyTorch/CLIP inference. 0 lets torch choose. "
            "Set 2-4 on small CPU hosts to avoid oversubscription."
        ),
    )
    clip_torch_interop_threads: int = Field(
        default=1,
        description="PyTorch inter-op threads for CLIP inference when running on CPU.",
    )
    text_embed_cache_size: int = Field(
        default=512,
        description="In-process LRU cache size for repeated CLIP text embeddings.",
    )
    embedding_dim: int = Field(
        default=512,
        description="Dimensionality of CLIP embeddings (clip-ViT-B-32 -> 512).",
    )

    # --- Source configuration ------------------------------------------------
    enabled_sources: list[str] = Field(
        default_factory=lambda: ["wikimedia"],
        description="Default stock sources; can be overridden per request/item.",
    )
    # Optional process-wide Flickr key. The orchestrator may also send a Flickr
    # key per request (credentials.flickr); when it doesn't, the Flickr source
    # falls back to this env value so editorial routing works without the
    # frontend having to supply a key.
    flickr_api_key: str | None = Field(
        default=None, description="Fallback Flickr API key (FLICKR_API_KEY)."
    )
    flickr_license: str = Field(
        default="4,5,7,8,9,10",
        description=(
            "Comma-separated Flickr license IDs to allow (default = commercial- "
            "and derivative-safe: CC BY, CC BY-SA, Flickr Commons/no-known- "
            "copyright, US Gov work, CC0, Public Domain Mark). Excludes NC/ND."
        ),
    )
    # Openverse works anonymously (rate-limited). An optional OAuth2 bearer token
    # (free, register an app at https://api.openverse.org/v1/auth_tokens/register/)
    # raises the rate limit; when unset the source still works keyless.
    openverse_token: str | None = Field(
        default=None, description="Optional Openverse bearer token (OPENVERSE_TOKEN)."
    )
    openverse_license_type: str = Field(
        default="commercial,modification",
        description=(
            "Openverse license_type filter (default keeps only commercially usable "
            "and modifiable works)."
        ),
    )

    # --- Worker / job lifecycle ---------------------------------------------
    worker_poll_interval_s: float = Field(
        default=1.0, description="How often the worker polls for queued jobs."
    )
    job_running_timeout_s: float = Field(
        default=300.0,
        description="A job stuck in 'running' longer than this is re-queued.",
    )
    job_deadline_s: float = Field(
        default=240.0,
        description=(
            "In-process wall-clock deadline for run_job. Kept BELOW "
            "job_running_timeout_s so a hung job fails cleanly (marked failed) "
            "rather than being treated as an orphan and requeued forever. The "
            "single worker processes one job at a time, so this is what stops a "
            "hung item from freezing the whole queue."
        ),
    )
    job_heartbeat_interval_s: float = Field(
        default=15.0,
        description="How often the running worker refreshes jobs.heartbeat_at.",
    )
    job_stale_timeout_s: float = Field(
        default=120.0,
        description=(
            "How old heartbeat_at can get before a running job is treated as "
            "orphaned and requeued or failed."
        ),
    )
    job_stale_sweep_interval_s: float = Field(
        default=30.0,
        description="How often the worker scans running jobs for stale heartbeats.",
    )
    job_max_attempts: int = Field(
        default=3,
        description="Maximum running attempts before a stale job is marked failed.",
    )
    job_ttl_s: float = Field(
        default=3600.0,
        description="Done/failed jobs older than this are pruned even if unfetched.",
    )

    # --- Input validation caps ----------------------------------------------
    max_items_per_job: int = Field(
        default=512,
        description=(
            "Cap on items per job. Orchestrator may submit multiple keyword "
            "queries per beat to improve matching quality (e.g. a long, ~70-beat "
            "narration at 3 queries/beat is ~210 items)."
        ),
    )
    max_sources_per_item: int = Field(default=8, description="Cap on sources per item.")
    max_keyword_length: int = Field(default=256, description="Cap on keyword length.")
    max_text_embed_texts: int = Field(
        default=128,
        description="Maximum number of strings accepted by the utility /text-embed endpoint.",
    )

    # --- Pipeline defaults ---------------------------------------------------
    default_per_page: int = Field(default=15, description="Results per source query.")
    default_min_score: float = Field(
        default=0.20, description="Default cosine threshold for returned assets."
    )
    max_assets_per_item: int = Field(
        default=8, description="Cap on assets returned per item."
    )
    preview_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        description="Maximum bytes to download for a single preview image before skipping it.",
    )
    preview_total_timeout_s: float = Field(
        default=15.0,
        description=(
            "Total wall-clock cap for downloading a single preview image. Guards "
            "against a slow/slowloris CDN that drips bytes under the per-read "
            "timeout and would otherwise hold a download slot indefinitely."
        ),
    )
    image_embed_batch_size: int = Field(
        default=24,
        description=(
            "How many preview images to decode/embed in one CLIP batch. Lower values "
            "reduce peak RAM; higher values may be slightly faster."
        ),
    )
    item_concurrency: int = Field(
        default=3,
        description=(
            "How many keyword items in a job are processed at once. Overlaps each "
            "item's source searches + preview downloads with another item's CLIP "
            "embedding. CLIP embedding itself is serialized (one CPU model), so "
            "keep this modest (2-4); it mainly hides network latency, not CPU."
        ),
    )
    enable_cache_first: bool = Field(
        default=False,
        description=(
            "Reuse previously embedded assets via vector search before hitting "
            "sources. Kept OFF by default: within one video most beats share a "
            "topic, so cache-first makes every beat collapse onto the same handful "
            "of cached images. Off => each beat fetches fresh, diverse results."
        ),
    )

    # --- Outbound HTTP -------------------------------------------------------
    http_timeout_s: float = Field(default=20.0, description="Outbound HTTP timeout.")
    http_user_agent: str = Field(
        default="FacelessFlow/1.0 (https://github.com/faceless-video; faceless-video@proton.me)",
        description=(
            "User-Agent sent to all outbound source requests. Wikimedia's "
            "policy requires a meaningful UA with contact info "
            "(https://meta.wikimedia.org/wiki/User-Agent_policy); a blank or "
            "browser-like UA gets throttled/blocked. Format: "
            "'AppName/Version (contact URL; email)'. Override via HTTP_USER_AGENT "
            "with your own real contact details."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance for the process."""

    return Settings()  # type: ignore[call-arg]  # values come from the environment
