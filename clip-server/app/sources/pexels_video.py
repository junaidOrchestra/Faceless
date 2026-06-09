"""Pexels video search — embed the preview frame, pick best file as media_url."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Candidate, StockSource, quality_target_width
from .registry import register_source

logger = logging.getLogger(__name__)

_PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


def _pick_video_file(
    video_files: list[dict[str, Any]], target_width: int
) -> dict[str, Any] | None:
    """Pick the smallest mp4 whose width still covers ``target_width``.

    Pexels often returns the same clip in SD/HD/UHD. Choosing the smallest file
    that still meets the target resolution avoids downloading a 4K master just to
    downscale it to a 1080p timeline. For the ``max`` tier (huge target width) no
    file "covers" it, so we fall through to the largest available.
    """

    mp4s = [f for f in video_files if (f.get("file_type") or "").endswith("mp4")]
    if not mp4s:
        return video_files[0] if video_files else None
    covering = sorted(
        (f for f in mp4s if int(f.get("width") or 0) >= target_width),
        key=lambda f: int(f.get("width") or 0),
    )
    if covering:
        return covering[0]
    return max(mp4s, key=lambda f: int(f.get("width") or 0))


@register_source
class PexelsVideoSource(StockSource):
    """Search Pexels /videos/search; preview is the video's picture frame."""

    name = "pexels_video"
    platform = "pexels"
    requires_key = True
    credential_key = "pexels"
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

        target_width = quality_target_width(options)
        candidates: list[Candidate] = []
        for video in payload.get("videos", [])[:n]:
            preview = video.get("image")
            chosen = _pick_video_file(video.get("video_files") or [], target_width)
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
                    raw={"url": video.get("url"), "width": video.get("width"), "height": video.get("height")},
                )
            )
        return candidates
