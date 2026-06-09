"""Flickr photo search — real, editorial/archive imagery for named people/events.

Used by the orchestrator's "editorial" beat routing (historical personalities,
world leaders, celebrities, and specific named historical events), where generic
stock libraries do a poor job and authentic photographs are wanted.

Only commercial- and derivative-safe licenses are returned by default (CC BY,
CC BY-SA, Flickr Commons / "no known copyright", US Government works, CC0, and
Public Domain Mark); the allowed set is configurable via ``FLICKR_LICENSE``.

The API key comes from the per-request ``credentials['flickr']`` when present,
otherwise from the process-wide ``FLICKR_API_KEY`` (so editorial routing works
without the frontend supplying a key).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings
from .base import Candidate, StockSource, quality_target_width
from .registry import register_source

logger = logging.getLogger(__name__)

_FLICKR_API = "https://api.flickr.com/services/rest/"

# Flickr license id -> human-readable name (for attribution display).
_LICENSE_NAMES: dict[str, str] = {
    "0": "All Rights Reserved",
    "1": "CC BY-NC-SA 2.0",
    "2": "CC BY-NC 2.0",
    "3": "CC BY-NC-ND 2.0",
    "4": "CC BY 2.0",
    "5": "CC BY-SA 2.0",
    "6": "CC BY-ND 2.0",
    "7": "No known copyright restrictions",
    "8": "United States Government Work",
    "9": "Public Domain Dedication (CC0)",
    "10": "Public Domain Mark",
}

# Flickr "extras" size suffixes, smallest..largest, with their typical longest
# edge in pixels. We pick the smallest that still covers the requested quality
# target width (mirrors the Pexels video logic) so we don't pull a huge original
# just to downscale it. ``url_o`` (original) has no fixed size.
_SIZE_FIELDS: list[tuple[str, str, int]] = [
    ("url_m", "width_m", 500),
    ("url_z", "width_z", 640),
    ("url_c", "width_c", 800),
    ("url_l", "width_l", 1024),
    ("url_h", "width_h", 1600),
    ("url_k", "width_k", 2048),
    ("url_o", "width_o", 10**9),
]
_PREVIEW_FIELDS = ("url_n", "url_m", "url_z", "url_q", "url_c")
_EXTRAS = "owner_name,license,url_n,url_m,url_z,url_q,url_c,url_l,url_h,url_k,url_o"


def _pick_media(photo: dict[str, Any], target_width: int) -> tuple[str | None, int]:
    """Pick the smallest available size whose width covers ``target_width``.

    Returns ``(url, width)``; falls back to the largest available size when none
    covers the target (e.g. the ``max`` tier).
    """

    available: list[tuple[int, str]] = []
    for url_field, w_field, approx in _SIZE_FIELDS:
        url = photo.get(url_field)
        if not url:
            continue
        try:
            width = int(photo.get(w_field) or approx)
        except (TypeError, ValueError):
            width = approx
        available.append((width, url))
    if not available:
        return None, 0
    available.sort(key=lambda t: t[0])
    for width, url in available:
        if width >= target_width:
            return url, width
    return available[-1][1], available[-1][0]


def _pick_preview(photo: dict[str, Any]) -> str | None:
    for field in _PREVIEW_FIELDS:
        url = photo.get(field)
        if url:
            return url
    return None


@register_source
class FlickrSource(StockSource):
    """Search Flickr photos via ``flickr.photos.search`` (license-filtered)."""

    name = "flickr"
    platform = "flickr"
    requires_key = True
    credential_key = "flickr"
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
        settings = get_settings()
        api_key = credentials.get("flickr") or settings.flickr_api_key
        if not api_key:
            logger.warning("flickr skipped: no flickr credential or FLICKR_API_KEY")
            return []

        params: dict[str, Any] = {
            "method": "flickr.photos.search",
            "api_key": api_key,
            "text": query,
            "sort": "relevance",
            "content_type": 1,  # photos only
            "media": "photos",
            "safe_search": 1,
            "license": settings.flickr_license,
            "extras": _EXTRAS,
            "per_page": min(max(n, 1), 100),
            "page": 1,
            "format": "json",
            "nojsoncallback": 1,
        }
        response = await http_client.get(_FLICKR_API, params=params, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        if payload.get("stat") != "ok":
            logger.warning("flickr error for %r: %s", query, payload.get("message"))
            return []

        target_width = quality_target_width(options)
        photos = (payload.get("photos") or {}).get("photo") or []
        candidates: list[Candidate] = []
        for photo in photos[:n]:
            preview = _pick_preview(photo)
            media_url, _ = _pick_media(photo, target_width)
            if not preview or not media_url:
                continue
            owner = str(photo.get("owner") or "")
            photo_id = str(photo.get("id") or "")
            license_id = str(photo.get("license") or "")
            candidates.append(
                Candidate(
                    platform="flickr",
                    external_id=photo_id,
                    kind="photo",
                    preview_url=preview,
                    media_url=media_url,
                    attribution_name=photo.get("ownername") or owner or None,
                    attribution_url=(
                        f"https://www.flickr.com/photos/{owner}/{photo_id}"
                        if owner and photo_id
                        else None
                    ),
                    license=_LICENSE_NAMES.get(license_id, "Flickr"),
                    duration=None,
                    raw={"title": photo.get("title")},
                )
            )
        return candidates
