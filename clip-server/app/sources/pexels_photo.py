"""Pexels photo search (requires API key in request credentials)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Candidate, StockSource
from .registry import register_source

logger = logging.getLogger(__name__)

_PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"


@register_source
class PexelsPhotoSource(StockSource):
    """Search Pexels /v1/search and map photos to :class:`Candidate` records."""

    name = "pexels_photo"
    platform = "pexels"
    requires_key = True
    media_kinds = ("photo",)

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
            logger.warning("pexels_photo skipped: missing pexels credential")
            return []

        params: dict[str, Any] = {"query": query, "per_page": min(n, 80)}
        if options.get("orientation"):
            params["orientation"] = options["orientation"]

        response = await http_client.get(
            _PEXELS_PHOTO_URL,
            params=params,
            headers={"Authorization": api_key},
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()

        candidates: list[Candidate] = []
        for photo in payload.get("photos", [])[:n]:
            src = photo.get("src") or {}
            preview = src.get("medium") or src.get("small") or src.get("original")
            media = src.get("large2x") or src.get("large") or src.get("original")
            if not preview or not media:
                continue
            candidates.append(
                Candidate(
                    platform="pexels",
                    external_id=str(photo.get("id")),
                    kind="photo",
                    preview_url=preview,
                    media_url=media,
                    attribution_name=photo.get("photographer"),
                    attribution_url=photo.get("photographer_url"),
                    license="Pexels License",
                    duration=None,
                    raw=photo,
                )
            )
        return candidates
