"""Pexels video search — embed the preview frame, pick best file as media_url."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Candidate, StockSource
from .registry import register_source

logger = logging.getLogger(__name__)

_PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


def _pick_video_file(video_files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer HD mp4, then largest width — avoids tiny preview-quality files."""

    mp4s = [f for f in video_files if (f.get("file_type") or "").endswith("mp4")]
    if not mp4s:
        return video_files[0] if video_files else None
    hd = [f for f in mp4s if f.get("quality") == "hd"]
    pool = hd or mp4s
    return max(pool, key=lambda f: int(f.get("width") or 0))


@register_source
class PexelsVideoSource(StockSource):
    """Search Pexels /videos/search; preview is the video's picture frame."""

    name = "pexels_video"
    platform = "pexels"
    requires_key = True
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
        api_key = credentials.get("pexels")
        if not api_key:
            logger.warning("pexels_video skipped: missing pexels credential")
            return []

        params: dict[str, Any] = {"query": query, "per_page": min(n, 80)}
        if options.get("orientation"):
            params["orientation"] = options["orientation"]

        response = await http_client.get(
            _PEXELS_VIDEO_URL,
            params=params,
            headers={"Authorization": api_key},
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()

        candidates: list[Candidate] = []
        for video in payload.get("videos", [])[:n]:
            preview = video.get("image")
            chosen = _pick_video_file(video.get("video_files") or [])
            if not preview or not chosen or not chosen.get("link"):
                continue
            candidates.append(
                Candidate(
                    platform="pexels",
                    external_id=str(video.get("id")),
                    kind="video",
                    preview_url=preview,
                    media_url=chosen["link"],
                    attribution_name=video.get("user", {}).get("name"),
                    attribution_url=video.get("url"),
                    license="Pexels License",
                    duration=float(video.get("duration") or 0) or None,
                    raw=video,
                )
            )
        return candidates
