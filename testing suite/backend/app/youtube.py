"""Fetch the audio track of a YouTube video as a small mono MP3 via yt-dlp.

Runs the (blocking) yt-dlp download; callers should invoke :func:`fetch_audio`
through ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .config import Settings

logger = logging.getLogger(__name__)

# Cookies are the only reliable fix for these — surfaced to the user verbatim.
_AUTH_HINT = (
    "YouTube requires authentication for this video from this server "
    "(rate-limited / bot-checked). Drop a cookies.txt exported from a "
    "logged-in browser into the 'cookies' folder next to docker-compose.yml "
    "and it will be picked up automatically (see README)."
)


def _resolve_cookies(settings: Settings) -> str | None:
    """Explicit cookies file, else the first cookies file found in the dir."""
    explicit = settings.youtube_cookies_file
    if explicit and Path(explicit).is_file():
        return explicit
    cdir = Path(settings.youtube_cookies_dir)
    if cdir.is_dir():
        preferred = cdir / "cookies.txt"
        if preferred.is_file():
            return str(preferred)
        for txt in sorted(cdir.glob("*.txt")):
            if txt.is_file():
                return str(txt)
    return None


@dataclass(slots=True)
class FetchedAudio:
    path: str
    title: str
    duration_s: float
    video_id: str
    size_bytes: int


def fetch_audio(url: str, out_dir: str, settings: Settings) -> FetchedAudio:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    clients = [c.strip() for c in settings.youtube_player_clients.split(",") if c.strip()]
    ydl_opts: dict = {
        "format": settings.youtube_audio_format,
        "outtmpl": str(out / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        # Treat an empty/zero-byte download as a hard failure (so we can retry).
        "abort_on_unavailable_fragments": True,
        # Be gentle to avoid tripping YouTube's rate limiter, and let yt-dlp
        # retry its own transient HTTP errors before we do.
        "retries": 5,
        "extractor_retries": 3,
        "sleep_interval_requests": 1,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": settings.audio_bitrate_kbps,
            }
        ],
        # Mono + 16 kHz: ideal for speech transcription and tiny on disk.
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
    }
    extractor_args: dict = {}
    # Optionally pin innertube clients (empty = let yt-dlp choose its defaults).
    if clients:
        extractor_args["youtube"] = {"player_client": clients}
    # Point the bgutil PO-token plugin at the provider sidecar so yt-dlp can
    # mint the token YouTube now requires for the good (non-HLS) formats.
    if settings.pot_provider_url:
        extractor_args["youtubepot-bgutilhttp"] = {
            "base_url": [settings.pot_provider_url]
        }
    if extractor_args:
        ydl_opts["extractor_args"] = extractor_args

    cookies = _resolve_cookies(settings)
    if cookies:
        ydl_opts["cookiefile"] = cookies
        logger.info("using YouTube cookies from %s", cookies)

    info = None
    attempts = max(1, settings.youtube_fetch_retries)
    for attempt in range(1, attempts + 1):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except DownloadError as exc:
            msg = str(exc)
            rate_limited = "429" in msg or "Too Many Requests" in msg
            bot_checked = "Sign in to confirm" in msg or "not a bot" in msg

            # Transient throttling without cookies: back off and retry.
            if (rate_limited or bot_checked) and attempt < attempts and not cookies:
                wait = settings.youtube_retry_backoff_s * attempt
                logger.warning(
                    "yt-dlp throttled (attempt %s/%s), retrying in %.0fs: %s",
                    attempt, attempts, wait, msg.splitlines()[-1] if msg else "",
                )
                time.sleep(wait)
                continue

            if rate_limited or bot_checked:
                # Out of retries (or cookies present but still blocked).
                raise RuntimeError(_AUTH_HINT) from exc
            if "file is empty" in msg or "Requested format is not available" in msg:
                raise RuntimeError(
                    "Could not fetch a downloadable audio stream. " + _AUTH_HINT
                ) from exc
            raise RuntimeError(msg) from exc

    if info is None:
        raise RuntimeError("yt-dlp returned no metadata for this URL")

    video_id = str(info.get("id") or "audio")
    title = str(info.get("title") or video_id)
    duration_s = float(info.get("duration") or 0.0)

    mp3_path = out / f"{video_id}.mp3"
    if not mp3_path.exists():
        # Fallback: find the produced file for this id.
        matches = sorted(out.glob(f"{video_id}.*"))
        if not matches:
            raise RuntimeError("audio extraction produced no output file")
        mp3_path = matches[0]

    size = mp3_path.stat().st_size
    if size > settings.max_upload_bytes:
        raise RuntimeError(
            f"extracted audio is {size // (1024 * 1024)} MB, over the "
            f"{settings.max_upload_bytes // (1024 * 1024)} MB upload limit — "
            f"try a shorter video or a lower AUDIO_BITRATE_KBPS"
        )

    return FetchedAudio(
        path=str(mp3_path),
        title=title,
        duration_s=duration_s,
        video_id=video_id,
        size_bytes=size,
    )
