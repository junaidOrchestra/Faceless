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

    llm_provider: Literal["gemini", "cerebras", "local", "stub"] = "stub"
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

    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    worker_poll_interval_s: float = 1.0
    job_running_timeout_s: float = 900.0
    clip_poll_interval_s: float = 2.0
    clip_poll_timeout_s: float = 300.0

    max_upload_bytes: int = 50 * 1024 * 1024
    render_temp_dir: str = "/tmp/faceless-render"
    result_base_url: str = Field(
        default="file:///tmp/faceless-results",
        description="Prefix used when storing result_url for completed videos.",
    )

    default_sources: list[str] = Field(default_factory=lambda: ["stub"])
    default_user_id: str = "anonymous"

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
