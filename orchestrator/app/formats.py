"""Output format presets mapping social platforms to orientation + dimensions.

A single ``format`` string chosen by the caller drives two things:

* the Pexels ``orientation`` forwarded to the clip-server (so fetched stock
  media already matches the target aspect ratio), and
* the FFmpeg render dimensions (so the final mp4 is sized for the platform).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class VideoFormat:
    """A resolved output format."""

    name: str
    orientation: str  # Pexels value: "landscape" | "portrait" | "square"
    width: int
    height: int


# The accepted formats — one per target platform. These are the canonical
# values stored on the job; ``name`` is preserved as metadata.
ACCEPTED_FORMATS: dict[str, VideoFormat] = {
    "youtube": VideoFormat("youtube", "landscape", 1920, 1080),
    "youtube_shorts": VideoFormat("youtube_shorts", "portrait", 1080, 1920),
    "instagram_reels": VideoFormat("instagram_reels", "portrait", 1080, 1920),
    "tiktok": VideoFormat("tiktok", "portrait", 1080, 1920),
    "instagram_post": VideoFormat("instagram_post", "square", 1080, 1080),
}

# Convenience aliases -> a canonical format above. Lower-cased, non-alphanumerics
# collapsed to single underscores before lookup (see :func:`_normalize`).
_ALIASES: dict[str, str] = {
    "landscape": "youtube",
    "horizontal": "youtube",
    "16_9": "youtube",
    "shorts": "youtube_shorts",
    "reels": "instagram_reels",
    "instagram": "instagram_reels",
    "tiktok_video": "tiktok",
    "vertical": "tiktok",
    "portrait": "tiktok",
    "9_16": "tiktok",
    "square": "instagram_post",
    "1_1": "instagram_post",
}

DEFAULT_FORMAT = ACCEPTED_FORMATS["youtube"]


def valid_formats() -> list[str]:
    """Sorted list of canonical ``format`` values (for error messages/docs)."""

    return sorted(ACCEPTED_FORMATS)


def search_orientation(orientation: str | None) -> str | None:
    """Orientation filter to forward to the stock provider (Pexels).

    Portrait (9:16) outputs — shorts/reels/tiktok — intentionally search WITHOUT
    an orientation filter: Pexels' portrait inventory is comparatively small, so
    constraining to it starves results. Cover-scaling/cropping a landscape clip
    to vertical at render time gives better coverage than a thin portrait-only
    pool. Landscape (16:9) and square keep their filter so widescreen output
    still gets aspect-matched media.
    """

    if orientation == "portrait":
        return None
    return orientation


def _normalize(value: str) -> str:
    out = []
    for ch in value.strip().lower():
        out.append(ch if ch.isalnum() else "_")
    # Collapse runs of underscores.
    normalized = "_".join(part for part in "".join(out).split("_") if part)
    return normalized


def resolve_format(value: str | None) -> VideoFormat:
    """Resolve a caller-supplied ``format`` string to a :class:`VideoFormat`.

    Returns :data:`DEFAULT_FORMAT` when ``value`` is empty. Raises ``ValueError``
    for a non-empty but unrecognized value so the API can return a clear 400.
    """

    if not value:
        return DEFAULT_FORMAT
    key = _normalize(value)
    # Resolve an alias to its canonical name, then look up the format.
    key = _ALIASES.get(key, key)
    if key not in ACCEPTED_FORMATS:
        raise ValueError(
            f"Unknown format {value!r}. Valid options: {', '.join(valid_formats())}."
        )
    return ACCEPTED_FORMATS[key]
