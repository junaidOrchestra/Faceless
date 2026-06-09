"""Normalize an uploaded audio (or video) file into the same small mono MP3 the
YouTube path produces, so everything downstream is identical.

Runs blocking ffmpeg/ffprobe; call through ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .config import Settings
from .youtube import FetchedAudio

logger = logging.getLogger(__name__)


def _probe_duration(path: str) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        return float(data.get("format", {}).get("duration") or 0.0)
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return 0.0


def prepare_uploaded_audio(
    src_path: str, out_dir: str, settings: Settings, original_name: str
) -> FetchedAudio:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "narration.mp3"

    # -vn drops any video track (so a video upload yields just its audio), then
    # downmix to mono 16 kHz at the configured bitrate — tiny and well under the
    # orchestrator's upload limit.
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        f"{settings.audio_bitrate_kbps}k",
        str(dst),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not dst.exists():
        tail = (res.stderr or "").strip()[-500:]
        raise RuntimeError(f"ffmpeg could not decode the uploaded file: {tail}")

    size = dst.stat().st_size
    if size > settings.max_upload_bytes:
        raise RuntimeError(
            f"converted audio is {size // (1024 * 1024)} MB, over the "
            f"{settings.max_upload_bytes // (1024 * 1024)} MB upload limit — "
            f"try a shorter clip or a lower AUDIO_BITRATE_KBPS"
        )

    title = Path(original_name).stem or "audio"
    return FetchedAudio(
        path=str(dst),
        title=title,
        duration_s=_probe_duration(str(dst)),
        video_id=title,
        size_bytes=size,
    )
