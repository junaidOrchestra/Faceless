"""Hardware video encoder detection for ffmpeg segment encodes."""

from __future__ import annotations

import logging
import shutil
import subprocess
from functools import lru_cache

logger = logging.getLogger(__name__)

# Maps a logical encoder choice to ffmpeg `-c:v` and companion flags.
_ENCODER_PROFILES: dict[str, list[str]] = {
    "libx264": [],  # preset/crf supplied by caller
    "h264_nvenc": [
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p4",
        "-rc",
        "vbr",
        "-cq",
        "23",
        "-b:v",
        "0",
    ],
    "h264_qsv": [
        "-c:v",
        "h264_qsv",
        "-global_quality",
        "23",
        "-look_ahead",
        "0",
    ],
}


@lru_cache(maxsize=1)
def _ffmpeg_encoders() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ""
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return proc.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


@lru_cache(maxsize=1)
def _nvenc_usable() -> bool:
    """True when h264_nvenc is listed AND can open (CUDA present)."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or "h264_nvenc" not in _ffmpeg_encoders():
        return False
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=64x64:d=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if proc.returncode != 0:
            logger.info(
                "h264_nvenc listed but unavailable at runtime (no GPU/CUDA); "
                "falling back to software encode"
            )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=1)
def _qsv_usable() -> bool:
    """True when h264_qsv is listed AND can open (Intel QSV present)."""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or "h264_qsv" not in _ffmpeg_encoders():
        return False
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=64x64:d=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "h264_qsv",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if proc.returncode != 0:
            logger.info(
                "h264_qsv listed but unavailable at runtime; falling back to software encode"
            )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def resolve_video_encoder(preference: str = "auto") -> str:
    """Pick ``libx264``, ``h264_nvenc``, or ``h264_qsv`` based on config + ffmpeg.

    ``auto`` prefers NVENC, then QSV, then software libx264. Hardware encoders are
    probed with a tiny test encode — ffmpeg may list NVENC without CUDA (common in
    CPU-only containers), which would otherwise fail every segment with
    ``Cannot load libcuda.so.1``.
    """

    pref = (preference or "auto").strip().lower()
    if pref in _ENCODER_PROFILES and pref != "auto":
        if pref == "libx264":
            return pref
        if pref == "h264_nvenc":
            return pref if _nvenc_usable() else "libx264"
        if pref == "h264_qsv":
            return pref if _qsv_usable() else "libx264"
        encoders = _ffmpeg_encoders()
        return pref if pref in encoders else "libx264"

    if _nvenc_usable():
        logger.info("render encoder: h264_nvenc (auto-detected)")
        return "h264_nvenc"
    if _qsv_usable():
        logger.info("render encoder: h264_qsv (auto-detected)")
        return "h264_qsv"
    logger.info("render encoder: libx264 (no usable hardware encoder)")
    return "libx264"


def video_encode_args(encoder: str, *, preset: str, crf: int) -> list[str]:
    """Return ffmpeg video encode flags for the chosen encoder."""

    key = resolve_video_encoder(encoder) if encoder == "auto" else encoder
    if key not in _ENCODER_PROFILES:
        key = "libx264"
    if key == "libx264":
        return [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
        ]
    return list(_ENCODER_PROFILES[key])
