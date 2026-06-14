"""Curated effect-overlay persistence.

Pre-fetched transition/overlay clips (one small set per visual ``category``)
served straight from Postgres so the editor never has to run a live, heavy
clip-server search on every "Add effect". Reads power ``GET /effects/overlays``;
``replace_category`` is used by the ``seed_effect_overlays.py`` refresh script.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EffectOverlay


async def list_active_overlays(
    session: AsyncSession,
) -> dict[str, list[EffectOverlay]]:
    """Return active overlays grouped by category, best (lowest rank) first."""

    result = await session.execute(
        select(EffectOverlay)
        .where(EffectOverlay.active.is_(True))
        .order_by(EffectOverlay.category, EffectOverlay.rank, EffectOverlay.id)
    )
    grouped: dict[str, list[EffectOverlay]] = defaultdict(list)
    for row in result.scalars():
        grouped[row.category].append(row)
    return dict(grouped)


async def replace_category(
    session: AsyncSession,
    category: str,
    rows: list[dict[str, Any]],
) -> int:
    """Replace all overlays for ``category`` with ``rows`` (idempotent reseed).

    Each entry in ``rows`` may carry ``media_url`` (required), ``preview_url``,
    ``source``, ``external_id``, ``attribution``, ``width``, ``height`` and
    ``duration_s``; ``rank`` is assigned by list order. Returns the count
    inserted. Commits the transaction.
    """

    await session.execute(
        delete(EffectOverlay).where(EffectOverlay.category == category)
    )
    inserted = 0
    seen: set[str] = set()
    for rank, row in enumerate(rows):
        media_url = (row.get("media_url") or "").strip()
        if not media_url or media_url in seen:
            continue
        seen.add(media_url)
        session.add(
            EffectOverlay(
                category=category,
                source=(row.get("source") or "pexels"),
                external_id=row.get("external_id"),
                media_url=media_url,
                preview_url=row.get("preview_url"),
                attribution=row.get("attribution"),
                width=row.get("width"),
                height=row.get("height"),
                duration_s=row.get("duration_s"),
                rank=rank,
                active=True,
            )
        )
        inserted += 1
    await session.commit()
    return inserted
