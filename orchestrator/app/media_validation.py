"""Server-side validation that a file is genuinely decodable audio/video media.

The upload endpoint already checks the client-declared content type against an
allow-list, but a declared type is trivially spoofable. These two independent
checks run on the bytes themselves, before they are persisted to durable storage
or handed to whisper/ffmpeg:

1. **Magic-byte sniff** (``filetype``): inspects the leading bytes and rejects a
   file whose *real* type is a concrete non-media type — an ``.exe``/``.zip``/
   ``.pdf`` renamed to ``.mp4`` is caught here regardless of the declared type.
   An unknown result is deferred to step 2 rather than rejected, so valid
   containers that ``filetype`` doesn't classify still get a fair chance.
2. **ffprobe decode probe** (hard timeout): the file must actually parse as media
   and expose at least one audio stream (the narration we transcribe). A
   truncated, corrupt, or non-media file fails here even when step 1 couldn't
   classify it, and the ``timeout`` guarantees a pathological file can't wedge
   the request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path

import filetype

logger = logging.getLogger(__name__)


class MediaValidationError(Exception):
    """A file is not an acceptable, decodable media file (client fault → 400)."""


def _sniff_mime(path: Path) -> str | None:
    """Best-effort true MIME from the file's magic bytes (reads ~261 bytes)."""

    try:
        kind = filetype.guess(str(path))
    except Exception:  # noqa: BLE001 - a sniff failure must never crash an upload
        logger.warning("magic-byte sniff failed for %s", path, exc_info=True)
        return None
    return kind.mime if kind else None


def _probe_media(path: Path, timeout_s: float) -> tuple[list[str], float | None]:
    """Return stream codec types and container duration via ffprobe, or raise.

    ``timeout`` makes ``subprocess.run`` SIGKILL ffprobe on expiry so a malicious
    or pathological file cannot wedge the worker thread indefinitely.
    """

    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    data = json.loads(proc.stdout or "{}")
    codec_types = [str(stream.get("codec_type") or "") for stream in data.get("streams", [])]
    raw_duration = data.get("format", {}).get("duration")
    try:
        duration_s = float(raw_duration) if raw_duration is not None else None
    except (TypeError, ValueError):
        duration_s = None
    return codec_types, duration_s


async def validate_media_file(
    path: Path,
    *,
    probe_timeout_s: float,
    require_audio: bool = True,
    max_duration_s: float | None = None,
) -> None:
    """Validate that ``path`` is a decodable audio/video file with an audio track.

    Raises :class:`MediaValidationError` with a user-safe message on a client
    fault (wrong content, corrupt media, no audio). A missing ``ffprobe`` binary
    is a server misconfiguration and is allowed to propagate (→ 500). The
    blocking ffprobe runs in a worker thread so the event loop stays free.
    """

    # 1) Magic-byte sniff: reject a file whose real type is a concrete non-media
    #    type. A None ("unknown") result defers to the ffprobe step below.
    mime = _sniff_mime(path)
    if mime is not None and not (mime.startswith("audio/") or mime.startswith("video/")):
        logger.warning("rejecting %s: sniffed non-media type %s", path, mime)
        raise MediaValidationError("File content is not an audio or video file.")

    # 2) ffprobe decode probe with a hard timeout.
    try:
        codec_types, duration_s = await asyncio.to_thread(_probe_media, path, probe_timeout_s)
    except subprocess.TimeoutExpired as exc:
        logger.warning("ffprobe timed out validating %s", path)
        raise MediaValidationError(
            "Could not validate the media file in time; try a smaller file."
        ) from exc
    except subprocess.CalledProcessError as exc:
        logger.warning("ffprobe rejected %s: %s", path, (exc.stderr or "").strip())
        raise MediaValidationError(
            "File is not a valid, decodable audio/video file."
        ) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("ffprobe produced unparsable output for %s", path)
        raise MediaValidationError(
            "File is not a valid, decodable audio/video file."
        ) from exc

    if not codec_types:
        raise MediaValidationError("File is not a valid, decodable audio/video file.")
    if require_audio and "audio" not in codec_types:
        raise MediaValidationError(
            "No audio track found — narration audio is required for transcription."
        )
    if (
        max_duration_s is not None
        and max_duration_s > 0
        and duration_s is not None
        and duration_s > max_duration_s
    ):
        raise MediaValidationError(
            f"Media is {duration_s:.0f}s but uploads are limited to {max_duration_s:.0f}s."
        )
