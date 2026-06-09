"""Per-item CLIP ranking pipeline (beat-agnostic).

For each job item the worker:

1. Queries every enabled source (failures are isolated per source).
2. Pools all candidates and reuses cached embeddings for any known asset.
3. Downloads/embeds only cache misses, then ranks by cosine similarity.
4. Upserts new survivors into the ``assets`` cache and attaches ranked rows to the item.

The opaque ``ref`` field is echoed untouched — we never parse it.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import httpx
import numpy as np
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.ext.asyncio import async_sessionmaker

from .config import Settings
from .embedding.base import Embedder
from .services import assets as asset_service
from .sources.base import Candidate
from .sources.registry import get_source

logger = logging.getLogger(__name__)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity for L2-normalized vectors (dot product)."""

    return float(np.dot(a, b))


async def _embed_texts(embedder: Embedder, lock: asyncio.Lock, texts: list[str]) -> np.ndarray:
    """Embed text off the event loop, serialized so one CPU model isn't reentered.

    ``embedder.embed_texts`` is a blocking, CPU-bound torch call. Running it via
    ``to_thread`` lets other items' network I/O proceed meanwhile (torch releases
    the GIL); the lock guarantees only one forward pass runs at a time, since a
    single CLIP model is not safe to call concurrently.
    """

    async with lock:
        return await asyncio.to_thread(embedder.embed_texts, texts)


async def _embed_images(
    embedder: Embedder,
    lock: asyncio.Lock,
    images: list[bytes],
    *,
    batch_size: int,
) -> np.ndarray:
    """Embed images in bounded chunks off the event loop.

    Decoding a large preview set all at once can hold many compressed blobs plus
    decoded RGB PIL images in memory. Chunking preserves ranking quality while
    reducing the peak allocation per CLIP forward pass.
    """

    if not images:
        return np.zeros((0, 0), dtype=np.float32)
    chunks: list[np.ndarray] = []
    size = max(1, batch_size)
    for start in range(0, len(images), size):
        batch = images[start : start + size]
        async with lock:
            chunks.append(await asyncio.to_thread(embedder.embed_images, batch))
    return np.vstack(chunks) if chunks else np.zeros((0, 0), dtype=np.float32)


def _stub_preview_bytes(url: str) -> bytes:
    """Build a tiny PNG for ``stub://`` URLs (tests never hit the network)."""

    from PIL import Image

    # Vary color by URL so CLIP stub vectors differ per candidate.
    seed = abs(hash(url)) % 255
    img = Image.new("RGB", (64, 64), color=(seed, (seed * 3) % 255, (seed * 7) % 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _is_decodable_image(blob: bytes) -> bool:
    """True if PIL recognizes the bytes as an image.

    A passing ``content-type: image/*`` header is not enough: stock CDNs can
    return HTML error pages, unsupported formats, or corrupt bodies with a 200.
    Use PIL's lightweight ``verify`` here so good images are fully decoded only
    once, during CLIP embedding.
    """

    try:
        with Image.open(io.BytesIO(blob)) as img:
            img.verify()
        return True
    except Exception:  # noqa: BLE001 - any decode failure means "unusable preview"
        return False


async def _download_preview(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    timeout_s: float | None = None,
) -> bytes | None:
    if url.startswith("stub://"):
        return _stub_preview_bytes(url)

    async def _read() -> bytes | None:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                return None
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = 0
                if declared_size > max_bytes:
                    logger.debug("preview too large for %s: %s bytes", url, content_length)
                    return None

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    logger.debug("preview exceeded %s bytes for %s", max_bytes, url)
                    return None
                chunks.append(chunk)
            return b"".join(chunks)

    try:
        # Total wall-clock cap per preview: a slow/slowloris CDN that streams
        # bytes under the per-read timeout would otherwise hold a download slot
        # indefinitely. A timed-out preview is simply skipped (returns None).
        if timeout_s is not None:
            return await asyncio.wait_for(_read(), timeout=timeout_s)
        return await _read()
    except Exception as exc:  # noqa: BLE001 - one bad preview must not fail the item
        logger.debug("preview download failed for %s: %s", url, exc)
        return None


async def _collect_unranked(
    settings: Settings,
    item: dict[str, Any],
    credentials: dict[str, str | None],
    options: dict[str, Any],
    http_client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Vibe-mode path: return raw source results WITHOUT CLIP embedding/ranking.

    Ambient "vibe" clips are random by design and never matched to specific text,
    so the expensive embed-preview + cosine-rank step is pure overhead here. We
    just fan out the source searches, dedupe by ``(platform, external_id)``, and
    return up to ``per_page`` candidates with their durations so the orchestrator
    can tile them along the narration timeline. Kept fully separate from the
    ranked path so neither can affect the other.
    """

    ref = item["ref"]
    keyword: str = item["keyword"]
    source_names: list[str] = item.get("sources") or settings.enabled_sources
    per_page = int(options.get("per_page") or settings.default_per_page)

    async def _search(name: str) -> list[Candidate]:
        try:
            source = get_source(name)
            if (
                source.requires_key
                and source.credential_key
                and not credentials.get(source.credential_key)
            ):
                return []
            return await source.search(
                keyword, per_page, credentials, options, http_client=http_client
            )
        except Exception as exc:  # noqa: BLE001 - one bad source must not fail the item
            logger.warning("unranked source %s failed for ref=%s: %s", name, ref, exc)
            return []

    pool: list[Candidate] = []
    for found in await asyncio.gather(*[_search(n) for n in source_names]):
        pool.extend(found)

    seen: set[tuple[str, str]] = set()
    assets: list[dict[str, Any]] = []
    for c in pool:
        key = (c.platform, c.external_id)
        if key in seen:
            continue
        seen.add(key)
        assets.append(
            {
                "platform": c.platform,
                "kind": c.kind,
                "media_url": c.media_url,
                "preview_url": c.preview_url,
                "attribution_name": c.attribution_name,
                "attribution_url": c.attribution_url,
                "license": c.license,
                "duration": c.duration,
                # Unranked: no cosine score, so use a neutral 1.0 (source order kept).
                "score": 1.0,
            }
        )
        if len(assets) >= per_page:
            break

    logger.info("unranked pool for ref=%s: %s clips (no embedding)", ref, len(assets))
    return {
        "ref": ref,
        "assets": assets,
        "error": None if assets else "No candidates found.",
    }


async def process_item(
    session: AsyncSession,
    embedder: Embedder,
    settings: Settings,
    item: dict[str, Any],
    credentials: dict[str, str | None],
    options: dict[str, Any],
    http_client: httpx.AsyncClient,
    embed_lock: asyncio.Lock,
) -> dict[str, Any]:
    """Process a single keyword item and return a result dict (ref + assets)."""

    # Vibe mode opts out of CLIP ranking — short-circuit to the raw-pool path.
    if not bool(options.get("rank", True)):
        return await _collect_unranked(settings, item, credentials, options, http_client)

    ref = item["ref"]
    keyword: str = item["keyword"]
    source_names: list[str] = item.get("sources") or settings.enabled_sources
    per_page = int(options.get("per_page") or settings.default_per_page)
    min_score = float(options.get("min_score") or settings.default_min_score)
    limit = settings.max_assets_per_item

    # Embed the keyword once; reused for both the cache search and source ranking.
    keyword_vec = (await _embed_texts(embedder, embed_lock, [keyword]))[0]

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
    # Every source is an independent HTTP round trip, so fan them out and await
    # together instead of serially. Failures stay isolated per source.
    pool: list[Candidate] = []
    source_errors: list[str] = []

    async def _search_source(name: str) -> list[Candidate]:
        try:
            source = get_source(name)
            if (
                source.requires_key
                and source.credential_key
                and not credentials.get(source.credential_key)
            ):
                return []
            return await source.search(
                keyword,
                per_page,
                credentials,
                options,
                http_client=http_client,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("source %s failed for ref=%s: %s", name, ref, exc)
            source_errors.append(f"{name}: {exc}")
            return []

    for found in await asyncio.gather(*[_search_source(n) for n in source_names]):
        pool.extend(found)

    if pool:
        # First reuse exact candidate cache hits by (platform, external_id). This
        # avoids downloading and re-embedding previews for stock items we have
        # already seen, while still allowing every fresh keyword to rescore the
        # cached embedding against its own text vector.
        candidate_keys = {(c.platform, c.external_id) for c in pool}
        cached_by_key = await asset_service.get_cached_assets_by_keys(session, candidate_keys)
        missing_pool: list[Candidate] = []
        seen_missing: set[tuple[str, str]] = set()
        cache_reused = 0

        for candidate in pool:
            key = (candidate.platform, candidate.external_id)
            cached = cached_by_key.get(key)
            if cached is not None:
                score = _cosine(keyword_vec, np.asarray(cached.embedding, dtype=np.float32))
                if score >= min_score:
                    existing = ranked_by_key.get(key)
                    if existing is None or score > existing[0]:
                        ranked_by_key[key] = (
                            score,
                            asset_service.asset_to_ranked(cached, score),
                        )
                cache_reused += 1
                continue
            if key not in seen_missing:
                seen_missing.add(key)
                missing_pool.append(candidate)

        if cache_reused:
            logger.info(
                "candidate cache reused for ref=%s (%s/%s candidates, skipped download/embed)",
                ref,
                cache_reused,
                len(pool),
            )

        # Download only cache misses in parallel (bounded concurrency).
        sem = asyncio.Semaphore(8)

        async def _fetch(candidate: Candidate) -> tuple[Candidate, bytes | None]:
            async with sem:
                blob = await _download_preview(
                    http_client,
                    candidate.preview_url,
                    max_bytes=settings.preview_max_bytes,
                    timeout_s=settings.preview_total_timeout_s,
                )
            return candidate, blob

        fetched = await asyncio.gather(*[_fetch(c) for c in missing_pool])
        # Keep only previews that actually decode — a bad blob here would
        # otherwise crash the batched embed and fail the whole item.
        candidates_with_preview: list[tuple[Candidate, bytes]] = []
        for candidate, blob in fetched:
            if blob is None:
                continue
            if not _is_decodable_image(blob):
                logger.debug(
                    "preview for %s:%s did not decode as an image; skipping",
                    candidate.platform,
                    candidate.external_id,
                )
                continue
            candidates_with_preview.append((candidate, blob))

        if candidates_with_preview:
            # CLIP image-embed the previews (batched), rank against the keyword.
            image_bytes = [blob for _, blob in candidates_with_preview]
            image_embeddings = await _embed_images(
                embedder,
                embed_lock,
                image_bytes,
                batch_size=settings.image_embed_batch_size,
            )
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
    sessionmaker: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    settings: Settings,
    items: list[dict[str, Any]],
    credentials: dict[str, str | None],
    options: dict[str, Any],
    *,
    embed_lock: asyncio.Lock | None = None,
) -> list[dict[str, Any]]:
    """Run the pipeline for every item in a job.

    Items run with bounded concurrency (``settings.item_concurrency``) so one
    item's network I/O (source searches + preview downloads) overlaps another
    item's CPU embedding. Each concurrent item gets its **own** DB session (an
    ``AsyncSession`` is not safe for concurrent use), and all CLIP embedding is
    serialized through a shared lock since there is a single CPU model. Results
    preserve input order.
    """

    headers = {"User-Agent": settings.http_user_agent}
    embed_lock = embed_lock or asyncio.Lock()
    sem = asyncio.Semaphore(max(1, settings.item_concurrency))

    async with httpx.AsyncClient(
        timeout=settings.http_timeout_s,
        headers=headers,
    ) as http_client:

        async def _run_one(item: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                try:
                    # Per-item session: concurrent items must not share one.
                    async with sessionmaker() as session:
                        return await process_item(
                            session,
                            embedder,
                            settings,
                            item,
                            credentials,
                            options,
                            http_client,
                            embed_lock,
                        )
                except Exception as exc:  # noqa: BLE001 - isolate one bad item
                    logger.exception("item failed ref=%s", item.get("ref"))
                    return {"ref": item.get("ref", "?"), "assets": [], "error": str(exc)}

        # gather preserves order, so results line up with `items`.
        return list(await asyncio.gather(*[_run_one(item) for item in items]))
