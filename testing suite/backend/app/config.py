"""Runtime configuration for the testing-suite backend.

Everything is read from the environment so the whole suite can be driven by the
`.env` next to docker-compose. Defaults point at the deployed orchestrator HF
Space (the same one seemless/.env.local uses), so `docker compose up` works with
zero extra setup.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _env(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


class Settings:
    # --- Orchestrator connection --------------------------------------------
    # Defaults match seemless/.env.local (deployed HF Space + its bearer token).
    orchestrator_url: str = _env(
        "ORCHESTRATOR_URL", "https://junaidorchestra-orchestrator.hf.space"
    ).rstrip("/")
    orchestrator_token: str = _env("ORCHESTRATOR_TOKEN", "orchestra-token-784631")

    # --- Clip search inputs forwarded on POST /videos -----------------------
    # seemless forces pexels_video + a pexels key; we mirror that so the test
    # videos use real stock footage.
    sources: str = _env("SOURCES", '["pexels_video"]')
    pexels_key: str = _env(
        "PEXELS_KEY", "y6T3FEbrm49ZEVp5XqkQINXcHQjvVkAs4iEKBdOgx3OfZvNS7rlOOBNu"
    )
    pixabay_key: str = _env("PIXABAY_KEY", "")

    # Per-beat source routing, mirroring the orchestrator's defaults
    # (orchestrator/app/config.py). The orchestrator routes named "person" and
    # "event" beats to these sources, and everything else to ``sources`` above.
    # Used only to *display* where each beat will go; the orchestrator does the
    # actual routing. Override to match a customized orchestrator .env.
    person_sources: str = _env("PERSON_SOURCES", '["openverse","pexels_video"]')
    event_sources: str = _env("EVENT_SOURCES", '["openverse","pexels_video"]')

    # --- Audio fetch ---------------------------------------------------------
    # Speech survives a low mono bitrate fine, which keeps the upload well under
    # the orchestrator's 50 MB limit even for long videos.
    audio_bitrate_kbps: str = _env("AUDIO_BITRATE_KBPS", "64")
    max_upload_bytes: int = _env_int("MAX_UPLOAD_BYTES", 50 * 1024 * 1024)
    youtube_cookies_file: str = _env("YOUTUBE_COOKIES_FILE", "")
    # Folder auto-scanned for a cookies file (cookies.txt or any *.txt) when
    # YOUTUBE_COOKIES_FILE isn't set. Mounted from ./cookies by docker-compose,
    # so dropping a cookies.txt there "just works" — no env/compose edits.
    youtube_cookies_dir: str = _env("YOUTUBE_COOKIES_DIR", "/app/cookies")
    # Ride out transient HTTP 429s (YouTube throttling) with a few backoff retries.
    youtube_fetch_retries: int = _env_int("YOUTUBE_FETCH_RETRIES", 3)
    youtube_retry_backoff_s: float = _env_float("YOUTUBE_RETRY_BACKOFF_S", 20.0)
    # bgutil PO-token provider HTTP server (the pot-provider compose service).
    # With it, YouTube's gated http audio formats are downloadable without
    # cookies. Empty disables it (then gated videos need cookies instead).
    pot_provider_url: str = _env("POT_PROVIDER_URL", "http://pot-provider:4416")
    # yt-dlp format selector. Prefer an http (non-HLS) audio stream — available
    # once the PO token is supplied — then a progressive http stream with audio
    # (ffmpeg extracts just the audio). ``protocol^=http`` excludes HLS (m3u8),
    # whose fragments can download empty.
    youtube_audio_format: str = _env(
        "YOUTUBE_AUDIO_FORMAT",
        "bestaudio[protocol^=http]/bestaudio/best[protocol^=http][acodec!=none]/best",
    )
    # yt-dlp innertube player clients (comma-separated). Empty lets yt-dlp pick
    # its defaults, which work best alongside the PO-token provider.
    youtube_player_clients: str = _env("YOUTUBE_PLAYER_CLIENTS", "")

    # --- Pipeline behaviour --------------------------------------------------
    max_concurrency: int = _env_int("MAX_CONCURRENCY", 2)
    poll_interval_s: float = _env_float("POLL_INTERVAL_S", 3.0)
    # Generous overall ceiling per polling stage (clip search / render can be slow).
    stage_timeout_s: float = _env_float("STAGE_TIMEOUT_S", 2400.0)
    http_timeout_s: float = _env_float("HTTP_TIMEOUT_S", 120.0)

    # --- Storage -------------------------------------------------------------
    output_dir: str = _env("OUTPUT_DIR", "/app/output")
    work_dir: str = _env("WORK_DIR", "/app/work")


@lru_cache
def get_settings() -> Settings:
    return Settings()
