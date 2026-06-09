"""Pixabay photo search (requires API key in request credentials)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Candidate, StockSource, resolve_quality
from .registry import register_source

logger = logging.getLogger(__name__)

_PIXABAY_PHOTO_URL = "https://pixabay.com/api/"

# The app uses Pexels' orientation vocabulary (landscape/portrait/square).
# Pixabay only understands horizontal/vertical (no square), so we translate.
_ORIENTATION_MAP = {"landscape": "horizontal", "portrait": "vertical"}


@register_source
class PixabayPhotoSource(StockSource):
    """Search Pixabay images and map hits to :class:`Candidate` records."""

    name = "pixabay_photo"
    platform = "pixabay"
    requires_key = True
    credential_key = "pixabay"
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
        api_key = credentials.get("pixabay")
        if not api_key:
            logger.warning("pixabay_photo skipped: missing pixabay credential")
            return []

        # Pixabay authenticates via the ``key`` query param (no auth header).
        params: dict[str, Any] = {
            "key": api_key,
            "q": query,
            "image_type": "photo",
            "per_page": max(3, min(n, 200)),
            "safesearch": "true",
        }
        orientation = _ORIENTATION_MAP.get((options.get("orientation") or "").lower())
        if orientation:
            params["orientation"] = orientation

        response = await http_client.get(_PIXABAY_PHOTO_URL, params=params, timeout=20.0)
        response.raise_for_status()
        payload = response.json()

        quality = resolve_quality(options)
        candidates: list[Candidate] = []
        for hit in payload.get("hits", [])[:n]:
            # webformatURL is a ~640px render good for CLIP; the larger variants
            # are used downstream for rendering. fullHDURL/imageURL are only
            # present with full Pixabay API access, so they fall back gracefully.
            preview = hit.get("webformatURL")
            if quality == "sd":
                media = hit.get("webformatURL")
            elif quality == "max":
                media = (
                    hit.get("imageURL")
                    or hit.get("fullHDURL")
                    or hit.get("largeImageURL")
                    or hit.get("webformatURL")
                )
            else:  # hd
                media = hit.get("largeImageURL") or hit.get("webformatURL")
            if not preview or not media:
                continue
            candidates.append(
                Candidate(
                    platform="pixabay",
                    external_id=str(hit.get("id")),
                    kind="photo",
                    preview_url=preview,
                    media_url=media,
                    attribution_name=hit.get("user"),
                    attribution_url=hit.get("pageURL"),
                    license="Pixabay License",
                    duration=None,
                    raw={"pageURL": hit.get("pageURL"), "tags": hit.get("tags")},
                )
            )
        return candidates
