"""Wikimedia Commons search — no API key; commercial-OK licenses only."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .base import Candidate, StockSource, quality_target_width, resolve_quality
from .registry import register_source

logger = logging.getLogger(__name__)

_API = "https://commons.wikimedia.org/w/api.php"

# Licenses we allow (public domain / CC0 / CC-BY). Exclude NC and SA variants.
_ALLOWED_LICENSE_MARKERS = (
    "public domain",
    "cc0",
    "cc-zero",
    "cc-by",
    "creative commons attribution",
)
_FORBIDDEN_LICENSE_MARKERS = ("nc", "noncommercial", "sa", "sharealike", "by-sa", "by-nc")


def _license_ok(license_short: str | None, extmetadata: dict[str, Any]) -> bool:
    """Return True only when the asset is safe for commercial reuse."""

    blob = " ".join(
        filter(
            None,
            [
                (license_short or "").lower(),
                str(extmetadata.get("LicenseShortName", {}).get("value", "")).lower(),
                str(extmetadata.get("UsageTerms", {}).get("value", "")).lower(),
            ],
        )
    )
    if any(marker in blob for marker in _FORBIDDEN_LICENSE_MARKERS):
        return False
    return any(marker in blob for marker in _ALLOWED_LICENSE_MARKERS)


@register_source
class WikimediaSource(StockSource):
    """Search Wikimedia Commons via the MediaWiki API."""

    name = "wikimedia"
    platform = "wikimedia"
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
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}",
            "gsrlimit": str(min(n * 3, 50)),  # over-fetch; many hits fail license filter
            "gsrnamespace": "6",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": "640",
        }
        response = await http_client.get(_API, params=params, timeout=25.0)
        response.raise_for_status()
        data = response.json()

        quality = resolve_quality(options)
        target_width = quality_target_width(options)
        candidates: list[Candidate] = []
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            if len(candidates) >= n:
                break
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = info.get("mime") or ""
            if not mime.startswith("image/"):
                continue
            meta = info.get("extmetadata") or {}
            license_short = (meta.get("LicenseShortName") or {}).get("value")
            if not _license_ok(license_short, meta):
                continue

            title = page.get("title") or "File"
            thumb = info.get("thumburl") or info.get("url")
            full = info.get("url")
            if not thumb or not full:
                continue

            # Commons originals are often huge (multi-MB, 4000px+). For sd/hd serve
            # a width-scaled render via Special:FilePath; only 'max' uses the
            # original. The preview (640px thumb) is unchanged for cheap embedding.
            if quality == "max":
                media_url = full
            else:
                filename = title.split(":", 1)[1] if ":" in title else title
                scaled_name = quote(filename.replace(" ", "_"))
                media_url = (
                    f"https://commons.wikimedia.org/wiki/Special:FilePath/"
                    f"{scaled_name}?width={target_width}"
                )

            artist = (meta.get("Artist") or {}).get("value") or title
            file_page = f"https://commons.wikimedia.org/wiki/{quote(title.replace(' ', '_'))}"

            candidates.append(
                Candidate(
                    platform="wikimedia",
                    external_id=str(page.get("pageid")),
                    kind="photo",
                    preview_url=thumb,
                    media_url=media_url,
                    attribution_name=artist,
                    attribution_url=file_page,
                    license=license_short or "See Commons file page",
                    duration=None,
                    raw={"title": title},
                )
            )
        return candidates
