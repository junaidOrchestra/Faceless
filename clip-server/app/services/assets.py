"""Asset cache — deduplicate on (platform, external_id) and reuse embeddings."""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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


async def get_cached_assets_by_keys(
    session: AsyncSession,
    keys: set[tuple[str, str]],
) -> dict[tuple[str, str], Asset]:
    """Return cached assets keyed by ``(platform, external_id)``.

    Used after source search to avoid re-downloading/re-embedding candidates
    whose preview embedding is already in the asset cache.
    """

    if not keys:
        return {}
    clauses = [
        (Asset.platform == platform) & (Asset.external_id == external_id)
        for platform, external_id in keys
    ]
    # SQLAlchemy's tuple IN support varies by backend/dialect configuration with
    # vector columns in this stack, so build an OR expression explicitly.
    result = await session.execute(select(Asset).where(or_(*clauses)))
    return {(asset.platform, asset.external_id): asset for asset in result.scalars()}


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
    """Insert or refresh a cached asset row (embedding updated on conflict).

    Uses Postgres ``INSERT ... ON CONFLICT`` so this is atomic and safe under
    concurrent item processing: if two items embed the same ``(platform,
    external_id)`` at once, one inserts and the other updates rather than racing
    a SELECT-then-INSERT into a unique-constraint violation.
    """

    vector = embedding.astype(np.float32).tolist()
    values = {
        "platform": candidate.platform,
        "external_id": candidate.external_id,
        "kind": candidate.kind,
        "media_url": candidate.media_url,
        "preview_url": candidate.preview_url,
        "attribution_name": candidate.attribution_name,
        "attribution_url": candidate.attribution_url,
        "license": candidate.license,
        "duration": candidate.duration,
        "embedding": vector,
        "keyword": keyword,
    }
    stmt = pg_insert(Asset).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["platform", "external_id"],
        set_={
            "media_url": stmt.excluded.media_url,
            "preview_url": stmt.excluded.preview_url,
            "attribution_name": stmt.excluded.attribution_name,
            "attribution_url": stmt.excluded.attribution_url,
            "license": stmt.excluded.license,
            "duration": stmt.excluded.duration,
            "embedding": stmt.excluded.embedding,
            "keyword": stmt.excluded.keyword,
        },
    )
    await session.execute(stmt)
    await session.commit()

    # Re-read so callers get a fully-populated ORM row (incl. the generated id).
    refreshed = await get_cached_asset(session, candidate.platform, candidate.external_id)
    assert refreshed is not None  # just upserted
    return refreshed


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
