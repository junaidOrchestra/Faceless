"""Seed/refresh the curated ``effect_overlays`` table from a royalty-free source.

Fetching an overlay clip live on every "Add effect" (search -> clip-server ->
Pexels -> rank -> top match) is a heavy operation. Instead we pre-fetch a small
set per visual category ONCE with this script and serve them straight from the
DB via ``GET /effects/overlays``.

It reuses the clip-server's synchronous ``/search`` endpoint (which talks to
Pexels with the keys that already live on the clip-server), so no extra API
keys are needed on the orchestrator. Run it after applying migration 010:

    psql "$DATABASE_URL" -f migrations/010_effect_overlays.sql
    python seed_effect_overlays.py                 # all categories, 6 each
    python seed_effect_overlays.py --per 8 light_leak glitch   # subset

Requires the same env as the orchestrator (DATABASE_URL, CLIP_SERVER_URL,
CLIP_SERVER_SECRET). Re-running replaces a category's rows (idempotent).
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.clip_client.http import HttpClipClient
from app.config import get_settings
from app.db import get_sessionmaker
from app.services import effect_overlays as effect_overlay_service

logger = logging.getLogger("seed_effect_overlays")

# category (frontend EffectVisualId) -> royalty-free search phrase. Kept in sync
# with EFFECT_VISUALS in seemless/lib/effects.ts. Overlays are short motion clips
# composited over the previous frame, so we pull video results from Pexels.
CATEGORY_QUERIES: dict[str, str] = {
    "light_leak": "light leak overlay",
    "film_burn": "film burn overlay",
    "glitch": "glitch overlay transition",
    "bokeh": "bokeh lights overlay",
    "particles": "gold particles black background",
    "smoke": "smoke black background",
    "lens_flare": "lens flare overlay",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "categories",
        nargs="*",
        help="Categories to (re)seed. Default: all known categories.",
    )
    parser.add_argument(
        "--per", type=int, default=6, help="Clips to store per category (default 6)."
    )
    parser.add_argument(
        "--orientation",
        default=None,
        choices=[None, "landscape", "portrait", "square"],
        help="Optional provider orientation hint.",
    )
    return parser.parse_args()


async def _seed(categories: list[str], per: int, orientation: str | None) -> None:
    settings = get_settings()
    if not settings.clip_server_url:
        raise SystemExit("CLIP_SERVER_URL is not set — cannot fetch overlays.")

    client = HttpClipClient(settings.clip_server_url, settings.clip_server_secret)
    sessionmaker = get_sessionmaker()
    total = 0

    for category in categories:
        query = CATEGORY_QUERIES.get(category)
        if not query:
            logger.warning("skipping unknown category %r", category)
            continue
        try:
            # Over-fetch so dedupe/filter still leaves ~``per`` good clips.
            raw = await client.search(
                query, [("pexels_video", max(per * 2, per))], orientation=orientation
            )
        except Exception as exc:  # noqa: BLE001 - keep going on a single failure
            logger.error("search failed for %s (%r): %s", category, query, exc)
            continue

        rows = [
            {
                "media_url": a.get("media_url"),
                "preview_url": a.get("preview_url"),
                "source": a.get("platform") or "pexels",
                "attribution": a.get("attribution_name"),
                "duration_s": a.get("duration"),
            }
            for a in raw
            if a.get("kind") == "video" and a.get("media_url")
        ][:per]

        if not rows:
            logger.warning("no video results for %s (%r)", category, query)
            continue

        async with sessionmaker() as session:
            inserted = await effect_overlay_service.replace_category(
                session, category, rows
            )
        total += inserted
        logger.info("seeded %s overlay(s) for %s", inserted, category)

    logger.info("done — %s overlay(s) across %s categor(ies)", total, len(categories))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    categories = args.categories or list(CATEGORY_QUERIES)
    asyncio.run(_seed(categories, args.per, args.orientation))


if __name__ == "__main__":
    main()
