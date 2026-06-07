"""Pixabay video search — embed the video thumbnail, pick a renderable file."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Candidate, StockSource, resolve_quality
from .registry import register_source

logger = logging.getLogger(__name__)

_PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"

# File-size preference per quality tier (Pixabay sizes: large≈1080p, medium≈720p,
# small≈540p, tiny≈360p). All tiers fall back through the rest so we never miss a
# renderable file.
_FILE_PRIORITY_BY_QUALITY = {
    "sd": ("small", "tiny", "medium", "large"),
    "hd": ("medium", "large", "small", "tiny"),
    "max": ("large", "medium", "small", "tiny"),
}
_THUMB_PRIORITY = ("large", "medium", "small", "tiny")


def _pick_media_url(videos: dict[str, Any], quality: str) -> str | None:
    """Choose the mp4 matching the requested quality tier, falling back as needed."""

    for size in _FILE_PRIORITY_BY_QUALITY.get(quality, _FILE_PRIORITY_BY_QUALITY["hd"]):
        entry = videos.get(size) or {}
        if entry.get("url"):
            return entry["url"]
    return None


def _pick_thumbnail(videos: dict[str, Any]) -> str | None:
    """Pixabay attaches a ``thumbnail`` frame per size; take the largest one."""

    for size in _THUMB_PRIORITY:
        entry = videos.get(size) or {}
        if entry.get("thumbnail"):
            return entry["thumbnail"]
    return None


@register_source
class PixabayVideoSource(StockSource):
    """Search Pixabay videos; preview is the per-size thumbnail frame."""

    name = "pixabay_video"
    platform = "pixabay"
    requires_key = True
    credential_key = "pixabay"
    media_kinds = ("video",)

    async def search(
        self,
        query: str,
        n: int,
        credentials: dict[str, str | None],
        options: dict[str, Any],
        *,
        http_client: httpx.AsyncClient,
    ) -> list[Candidate]:
        api_key = credentials.get("pixabay")
        if not api_key:
            logger.warning("pixabay_video skipped: missing pixabay credential")
            return []

        # Pixabay's video API has no orientation filter, so options are ignored here.
        params: dict[str, Any] = {
            "key": api_key,
            "q": query,
            "per_page": max(3, min(n, 200)),
            "safesearch": "true",
        }

        response = await http_client.get(_PIXABAY_VIDEO_URL, params=params, timeout=20.0)
        response.raise_for_status()
        payload = response.json()

        quality = resolve_quality(options)
        candidates: list[Candidate] = []
        for hit in payload.get("hits", [])[:n]:
            videos = hit.get("videos") or {}
            media_url = _pick_media_url(videos, quality)
            preview = _pick_thumbnail(videos)
            if not media_url or not preview:
                continue
            candidates.append(
                Candidate(
                    platform="pixabay",
                    external_id=str(hit.get("id")),
                    kind="video",
                    preview_url=preview,
                    media_url=media_url,
                    attribution_name=hit.get("user"),
                    attribution_url=hit.get("pageURL"),
                    license="Pixabay License",
                    duration=float(hit.get("duration") or 0) or None,
                    raw=hit,
                )
            )
        return candidates
