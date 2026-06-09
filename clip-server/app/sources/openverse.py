"""Openverse image search — free, keyless source for editorial/real imagery.

Openverse (by WordPress/Creative Commons) aggregates openly-licensed images from
Flickr-CC, museums/GLAM institutions, Wikimedia and more. It is used by the
orchestrator's per-beat routing for "person" and "event" beats (real named
people / specific historical events), where generic stock does poorly.

No API key is required (anonymous requests are rate-limited). An optional bearer
token (``OPENVERSE_TOKEN``) raises the limit. Only commercially usable and
modifiable licenses are returned by default (``OPENVERSE_LICENSE_TYPE``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import get_settings
from .base import Candidate, StockSource
from .registry import register_source

logger = logging.getLogger(__name__)

_OPENVERSE_API = "https://api.openverse.org/v1/images/"


@register_source
class OpenverseSource(StockSource):
    """Search Openverse images (commercial-safe licenses, keyless)."""

    name = "openverse"
    platform = "openverse"
    requires_key = False
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
        del credentials
        settings = get_settings()
        params: dict[str, Any] = {
            "q": query,
            "page_size": min(max(n, 1), 50),
            "page": 1,
            "license_type": settings.openverse_license_type,
            "mature": "false",
            "filter_dead": "true",
        }
        headers = {}
        if settings.openverse_token:
            headers["Authorization"] = f"Bearer {settings.openverse_token}"

        response = await http_client.get(
            _OPENVERSE_API, params=params, headers=headers, timeout=20.0
        )
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results") or []
        candidates: list[Candidate] = []
        for item in results[:n]:
            full = item.get("url")
            preview = item.get("thumbnail") or full
            if not full or not preview:
                continue
            license_code = item.get("license") or ""
            license_version = item.get("license_version") or ""
            license_label = " ".join(
                part for part in [license_code.upper(), license_version] if part
            ) or "Openverse"
            candidates.append(
                Candidate(
                    platform="openverse",
                    external_id=str(item.get("id") or full),
                    kind="photo",
                    preview_url=preview,
                    media_url=full,
                    attribution_name=item.get("creator"),
                    attribution_url=item.get("foreign_landing_url")
                    or item.get("creator_url"),
                    license=license_label,
                    duration=None,
                    raw={"title": item.get("title"), "source": item.get("source")},
                )
            )
        return candidates
