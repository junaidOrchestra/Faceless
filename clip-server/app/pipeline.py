"""Per-item CLIP ranking pipeline (beat-agnostic).

For each job item the worker:

1. Queries every enabled source (failures are isolated per source).
2. Pools all candidates, downloads previews, batch-embeds images with CLIP.
3. Embeds the keyword text, ranks the pool by cosine similarity.
4. Upserts survivors into the ``assets`` cache and attaches ranked rows to the item.

The opaque ``ref`` field is echoed untouched — we never parse it.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import httpx
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .embedding.base import Embedder
from .services import assets as asset_service
from .sources.base import Candidate
from .sources.registry import get_source

logger = logging.getLogger(__name__)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for L2-normalized vectors (dot product)."""

    return float(np.dot(a, b))


def _stub_preview_bytes(url: str) -> bytes:
    """Build a tiny PNG for ``stub://`` URLs (tests never hit the network)."""

    from PIL import Image

    # Vary color by URL so CLIP stub vectors differ per candidate.
    seed = abs(hash(url)) % 255
    img = Image.new("RGB", (64, 64), color=(seed, (seed * 3) % 255, (seed * 7) % 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _download_preview(client: httpx.AsyncClient, url: str) -> bytes | None:
    if url.startswith("stub://"):
        return _stub_preview_bytes(url)
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return None
        return response.content
    except Exception as exc:  # noqa: BLE001 - one bad preview must not fail the item
        logger.debug("preview download failed for %s: %s", url, exc)
        return None


async def process_item(
    session: AsyncSession,
    embedder: Embedder,
    settings: Settings,
    item: dict[str, Any],
    credentials: dict[str, str | None],
    options: dict[str, Any],
    http_client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Process a single keyword item and return a result dict (ref + assets)."""

    ref = item["ref"]
    keyword: str = item["keyword"]
    source_names: list[str] = item.get("sources") or settings.enabled_sources
    per_page = int(options.get("per_page") or settings.default_per_page)
    min_score = float(options.get("min_score") or settings.default_min_score)
    limit = settings.max_assets_per_item

    # Embed the keyword once; reused for both the cache search and source ranking.
    keyword_vec = embedder.embed_texts([keyword])[0]

    # Resolve the providers behind the requested source names so the cache search
    # only returns assets from sources the caller actually asked for.
    allowed_platforms: set[str] = set()
    for name in source_names:
        try:
            allowed_platforms.add(get_source(name).platform)
        except KeyError:
            continue

    # Ranked results keyed by (platform, external_id) so cache hits and freshly
    # fetched assets are de-duplicated; we keep the higher score on collision.
    ranked_by_key: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    # --- CACHE-FIRST: reuse previously embedded assets and skip the network. ---
    if settings.enable_cache_first:
        cached_hits = await asset_service.search_cached_assets(
            session, keyword_vec, allowed_platforms or None, min_score, limit
        )
        for asset, score in cached_hits:
            ranked_by_key[(asset.platform, asset.external_id)] = (
                score,
                asset_service.asset_to_ranked(asset, score),
            )
        # Enough good cached matches -> return immediately, no source calls at all.
        if len(ranked_by_key) >= limit:
            top = sorted(ranked_by_key.values(), key=lambda r: r[0], reverse=True)[:limit]
            logger.info("cache hit for ref=%s (%s assets, no source calls)", ref, len(top))
            return {"ref": ref, "assets": [row[1] for row in top], "error": None}

    # --- Otherwise search the external sources to backfill the remainder. ---
    pool: list[Candidate] = []
    source_errors: list[str] = []
    for name in source_names:
        try:
            source = get_source(name)
            if source.requires_key and name.startswith("pexels") and not credentials.get("pexels"):
                continue
            found = await source.search(
                keyword,
                per_page,
                credentials,
                options,
                http_client=http_client,
            )
            pool.extend(found)
        except Exception as exc:  # noqa: BLE001
            logger.warning("source %s failed for ref=%s: %s", name, ref, exc)
            source_errors.append(f"{name}: {exc}")

    if pool:
        # Download previews in parallel (bounded concurrency).
        sem = asyncio.Semaphore(8)

        async def _fetch(candidate: Candidate) -> tuple[Candidate, bytes | None]:
            async with sem:
                blob = await _download_preview(http_client, candidate.preview_url)
            return candidate, blob

        fetched = await asyncio.gather(*[_fetch(c) for c in pool])
        candidates_with_preview = [(c, b) for c, b in fetched if b is not None]

        if candidates_with_preview:
            # CLIP image-embed the previews (batched), rank against the keyword.
            image_bytes = [blob for _, blob in candidates_with_preview]
            image_embeddings = embedder.embed_images(image_bytes)
            for (candidate, _), vec in zip(candidates_with_preview, image_embeddings, strict=True):
                score = _cosine(keyword_vec, vec)
                if score < min_score:
                    continue
                # Persist (dedup on platform/external_id) and merge into results.
                cached = await asset_service.upsert_asset(session, candidate, vec, keyword)
                key = (cached.platform, cached.external_id)
                existing = ranked_by_key.get(key)
                if existing is None or score > existing[0]:
                    ranked_by_key[key] = (score, asset_service.asset_to_ranked(cached, score))

    if not ranked_by_key:
        return {
            "ref": ref,
            "assets": [],
            "error": "; ".join(source_errors) if source_errors else "No candidates found.",
        }

    top = sorted(ranked_by_key.values(), key=lambda r: r[0], reverse=True)[:limit]
    return {"ref": ref, "assets": [row[1] for row in top], "error": None}


async def run_job(
    session: AsyncSession,
    embedder: Embedder,
    settings: Settings,
    items: list[dict[str, Any]],
    credentials: dict[str, str | None],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run the pipeline for every item in a job (sequential items, parallel previews inside)."""

    headers = {"User-Agent": settings.http_user_agent}
    async with httpx.AsyncClient(
        timeout=settings.http_timeout_s,
        headers=headers,
    ) as http_client:
        results: list[dict[str, Any]] = []
        for item in items:
            try:
                results.append(
                    await process_item(
                        session,
                        embedder,
                        settings,
                        item,
                        credentials,
                        options,
                        http_client,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("item failed ref=%s", item.get("ref"))
                results.append(
                    {
                        "ref": item.get("ref", "?"),
                        "assets": [],
                        "error": str(exc),
                    }
                )
        return results
