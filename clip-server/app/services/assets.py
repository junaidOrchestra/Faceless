"""Asset cache — deduplicate on (platform, external_id) and reuse embeddings."""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Asset
from ..sources.base import Candidate


async def get_cached_asset(
    session: AsyncSession,
    platform: str,
    external_id: str,
) -> Asset | None:
    result = await session.execute(
        select(Asset).where(Asset.platform == platform, Asset.external_id == external_id)
    )
    return result.scalar_one_or_none()


async def search_cached_assets(
    session: AsyncSession,
    query_vec: np.ndarray,
    platforms: set[str] | None,
    min_score: float,
    limit: int,
) -> list[tuple[Asset, float]]:
    """Return cached assets most similar to ``query_vec`` (cosine), above threshold.

    Backed by the HNSW index on ``assets.embedding`` (``vector_cosine_ops``). CLIP
    embeddings are L2-normalized, so cosine similarity = ``1 - cosine_distance``.
    We over-fetch then threshold so the index does the heavy lifting and Python only
    filters a small candidate set. ``platforms`` scopes the cache to the providers
    behind the caller's requested sources (e.g. {"pexels", "wikimedia"}).
    """

    vec = np.asarray(query_vec, dtype=np.float32).tolist()
    distance = Asset.embedding.cosine_distance(vec).label("distance")
    stmt = select(Asset, distance)
    if platforms:
        stmt = stmt.where(Asset.platform.in_(tuple(platforms)))
    # Over-fetch (index-ordered) so the post-threshold top-N is still well populated.
    stmt = stmt.order_by(distance).limit(max(limit * 4, limit))

    rows = (await session.execute(stmt)).all()
    results: list[tuple[Asset, float]] = []
    for asset, dist in rows:
        score = 1.0 - float(dist)
        if score >= min_score:
            results.append((asset, score))
        if len(results) >= limit:
            break
    return results


async def upsert_asset(
    session: AsyncSession,
    candidate: Candidate,
    embedding: np.ndarray,
    keyword: str,
) -> Asset:
    """Insert or refresh a cached asset row (embedding updated on conflict)."""

    existing = await get_cached_asset(session, candidate.platform, candidate.external_id)
    vector = embedding.astype(np.float32).tolist()

    if existing is not None:
        existing.media_url = candidate.media_url
        existing.preview_url = candidate.preview_url
        existing.attribution_name = candidate.attribution_name
        existing.attribution_url = candidate.attribution_url
        existing.license = candidate.license
        existing.duration = candidate.duration
        existing.embedding = vector
        existing.keyword = keyword
        await session.commit()
        await session.refresh(existing)
        return existing

    asset = Asset(
        platform=candidate.platform,
        external_id=candidate.external_id,
        kind=candidate.kind,
        media_url=candidate.media_url,
        preview_url=candidate.preview_url,
        attribution_name=candidate.attribution_name,
        attribution_url=candidate.attribution_url,
        license=candidate.license,
        duration=candidate.duration,
        embedding=vector,
        keyword=keyword,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


def asset_to_ranked(asset: Asset, score: float) -> dict[str, Any]:
    """Serialize a cached asset plus its score for the job result JSON."""

    return {
        "platform": asset.platform,
        "kind": asset.kind,
        "media_url": asset.media_url,
        "preview_url": asset.preview_url,
        "attribution_name": asset.attribution_name,
        "attribution_url": asset.attribution_url,
        "license": asset.license,
        "duration": asset.duration,
        "score": float(score),
    }
