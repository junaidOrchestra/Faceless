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

    # --- CLIP model ----------------------------------------------------------
    clip_model_name: str = Field(
        default="clip-ViT-B-32",
        description="sentence-transformers CLIP model id (loaded once at startup).",
    )
    clip_device: str = Field(default="cpu", description="Torch device for CLIP.")
    embedding_dim: int = Field(
        default=512,
        description="Dimensionality of CLIP embeddings (clip-ViT-B-32 -> 512).",
    )

    # --- Source configuration ------------------------------------------------
    enabled_sources: list[str] = Field(
        default_factory=lambda: ["wikimedia"],
        description="Default stock sources; can be overridden per request/item.",
    )

    # --- Worker / job lifecycle ---------------------------------------------
    worker_poll_interval_s: float = Field(
        default=1.0, description="How often the worker polls for queued jobs."
    )
    job_running_timeout_s: float = Field(
        default=300.0,
        description="A job stuck in 'running' longer than this is re-queued.",
    )
    job_ttl_s: float = Field(
        default=3600.0,
        description="Done/failed jobs older than this are pruned even if unfetched.",
    )

    # --- Input validation caps ----------------------------------------------
    max_items_per_job: int = Field(default=64, description="Cap on items per job.")
    max_sources_per_item: int = Field(default=8, description="Cap on sources per item.")
    max_keyword_length: int = Field(default=256, description="Cap on keyword length.")

    # --- Pipeline defaults ---------------------------------------------------
    default_per_page: int = Field(default=15, description="Results per source query.")
    default_min_score: float = Field(
        default=0.20, description="Default cosine threshold for returned assets."
    )
    max_assets_per_item: int = Field(
        default=8, description="Cap on assets returned per item."
    )
    enable_cache_first: bool = Field(
        default=True,
        description="Reuse previously embedded assets via vector search before hitting sources.",
    )

    # --- Outbound HTTP -------------------------------------------------------
    http_timeout_s: float = Field(default=20.0, description="Outbound HTTP timeout.")
    http_user_agent: str = Field(
        default="faceless-clip-server/0.1 (+https://example.com; contact@example.com)",
        description="User-Agent sent to sources (required by Wikimedia).",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance for the process."""

    return Settings()  # type: ignore[call-arg]  # values come from the environment
