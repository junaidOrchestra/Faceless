"""Vibe-mode clip pipeline (kept separate from the script-matching pipeline).

When a job's content theme is a *vibe* (not "match my script"), visuals are
ambient and unrelated to the words, so the CLIP-ranked matching does not apply.
Instead it stays deliberately simple:

1. :func:`submit_vibe_pool` cuts the narration into roughly equal ~7-8s beats and
   submits one UNRANKED search item per beat (``rank=False``), each fetching a
   few random vibe clips.
2. :func:`assemble_vibe_timeline` (called once that job is done) gives each beat
   one of its fetched clips (the rest become swap alternates) and sets the beat
   text to the transcript spoken during its window.

This module is deliberately self-contained — it touches only the job services it
needs and never the script-path functions in :mod:`app.pipeline` — so changes to
one flow cannot break the other.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import vibes as vibe_registry
from .clip_client.base import ClipClient
from .config import Settings
from .formats import search_orientation
from .llm.base import LLMProvider
from .services import video_jobs as job_service

logger = logging.getLogger(__name__)

# Vibe mode is intentionally simple: even ~7-8s beats, one clip per beat.
_BEAT_LEN_S = 7.5  # target beat length (beats land ~7-8s after even division)
_PER_BEAT = 3  # clips fetched per beat from the clip server (1 shown + alternates)


def _num_beats(total: float) -> int:
    """How many ~7-8s beats the narration splits into."""

    return max(1, round(total / _BEAT_LEN_S))


def _beat_windows(total: float) -> list[tuple[float, float]]:
    """Cut ``[0, total]`` into ``_num_beats`` equal segments (~7-8s each)."""

    n = _num_beats(total)
    seg = total / n
    return [(i * seg, total if i == n - 1 else (i + 1) * seg) for i in range(n)]


async def _build_vibe_keywords(llm: LLMProvider, job_id: str, vibe: str, count: int) -> list[str]:
    """Return ``count`` distinct-ish keywords for a vibe (LLM + curated fallback)."""

    seed = vibe_registry.vibe_keywords_seed(vibe)
    label = vibe_registry.vibe_label(vibe)
    llm_kw = await llm.theme_keywords(label, count, examples=seed[:6])

    pool: list[str] = []
    seen: set[str] = set()
    for raw in [*llm_kw, *seed]:
        phrase = " ".join(str(raw).split()).strip()
        key = phrase.lower()
        if phrase and key not in seen:
            seen.add(key)
            pool.append(phrase)
    if not pool:
        pool = ["abstract background"]

    random.Random(job_id).shuffle(pool)
    return [pool[i % len(pool)] for i in range(count)]


async def submit_vibe_pool(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    payload: dict[str, Any],
    beats: list[Any],
    vibe: str,
    *,
    llm: LLMProvider,
    clip_client: ClipClient,
) -> bool:
    """Submit one UNRANKED search item per ~7-8s beat (``_PER_BEAT`` clips each).

    Returns whether a CLIP job was submitted (caller moves the job to
    ``awaiting_clip``). The original transcription beats are left untouched here;
    they are re-segmented later in :func:`assemble_vibe_timeline` once the clips
    are available (we still need them for per-beat caption text).
    """

    credentials = payload.get("credentials") or {}
    sources: list[str] | None = payload.get("sources") or settings.default_sources
    fmt = payload.get("format") or {}
    orientation: str | None = search_orientation(fmt.get("orientation"))
    quality: str | None = payload.get("quality")

    total = float(beats[-1].end_s) if beats else 0.0
    # One search item per beat. A safety cap keeps very long narrations from
    # submitting an enormous job; any beats beyond the cap reuse the fetched
    # clips at assembly time.
    cap = max(1, settings.clip_max_items_per_job)
    num_items = min(_num_beats(total), cap)

    keywords = await _build_vibe_keywords(llm, job_id, vibe, num_items)
    clip_items = [
        {"ref": f"vibe:{i}", "keyword": kw, "sources": sources}
        for i, kw in enumerate(keywords)
    ]
    if not clip_items:
        return False

    logger.info(
        "job %s vibe '%s': fetching %s clips for each of %s beat item(s)",
        job_id,
        vibe,
        _PER_BEAT,
        len(clip_items),
    )
    await job_service.set_progress(session, job_id, "vibe_pool_search")
    await clip_client.submit(
        f"{job_id}-clip",
        clip_items,
        credentials,
        sources,
        orientation=orientation,
        quality=quality,
        rank=False,
        per_page=_PER_BEAT,
    )
    return True


def _asset_dict(asset: Any) -> dict[str, Any]:
    """Flatten a returned clip asset into the dict shape stored on candidates."""

    return {
        "platform": asset.platform,
        "kind": asset.kind or "video",
        "media_url": asset.media_url,
        "preview_url": asset.preview_url,
        "attribution": asset.attribution_name,
    }


def _item_clips(item: Any) -> list[dict[str, Any]]:
    """The (deduped) clips returned for a single beat's search item."""

    if item is None:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for asset in item.assets:
        if not asset.media_url or asset.media_url in seen:
            continue
        seen.add(asset.media_url)
        out.append(_asset_dict(asset))
    return out


def _global_pool(status: Any) -> list[dict[str, Any]]:
    """All clips across every item, deduped — fallback for beats with no hits."""

    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in status.items:
        for clip in _item_clips(item):
            if clip["media_url"] in seen:
                continue
            seen.add(clip["media_url"])
            pool.append(clip)
    return pool


def _text_for_window(beats: list[Any], start: float, end: float) -> str:
    """Transcript spoken during ``[start, end]`` (overlapping original beats)."""

    parts = [b.text for b in beats if b.start_s < end and b.end_s > start and b.text]
    return " ".join(" ".join(str(p).split()) for p in parts).strip()


def _candidate(clip: dict[str, Any], *, selected: bool) -> dict[str, Any]:
    return {
        "platform": clip["platform"],
        "kind": clip.get("kind") or "video",
        "media_url": clip["media_url"],
        "preview_url": clip.get("preview_url"),
        "score": 1.0,
        "attribution": clip.get("attribution"),
        "selected": selected,
    }


async def assemble_vibe_timeline(
    session: AsyncSession,
    job_id: str,
    vibe: str,
    status: Any,
) -> str:
    """Build ~7-8s beats and give each one of its fetched clips.

    ``status`` is the already-polled (done) clip job. Reads the original
    transcription beats (for caption text), replaces them with the fixed-length
    beats, and writes one assignment per beat: the chosen clip selected, the rest
    of that beat's fetched clips as swap alternates. Returns ``"ready"`` or
    ``"failed"`` (no clips returned at all).
    """

    by_ref = {item.ref: item for item in status.items}
    fallback = _global_pool(status)

    original_beats = await job_service.get_beats(session, job_id)
    total = float(original_beats[-1].end_s) if original_beats else 0.0

    if not fallback or total <= 0:
        await job_service.mark_failed(
            session,
            job_id,
            f"No vibe clips found for '{vibe}'. Check the source/API key.",
        )
        return "failed"

    windows = _beat_windows(total)
    used: set[str] = set()
    fb = 0  # rotating index into the fallback pool

    # Decide each beat's clip order first (so we can save beats, then assignments).
    new_beats: list[dict[str, Any]] = []
    ordered_by_beat: list[list[dict[str, Any]]] = []
    for idx, (start, end) in enumerate(windows):
        clips = _item_clips(by_ref.get(f"vibe:{idx}"))
        if not clips:
            # This beat's keyword returned nothing — borrow from the global pool.
            take = min(_PER_BEAT, len(fallback))
            clips = [fallback[(fb + k) % len(fallback)] for k in range(take)]
            fb += 1
        # Prefer a clip not used yet to avoid the same video back-to-back.
        primary = next((c for c in clips if c["media_url"] not in used), clips[0])
        used.add(primary["media_url"])
        ordered = [primary, *[c for c in clips if c["media_url"] != primary["media_url"]]]
        ordered_by_beat.append(ordered)
        new_beats.append(
            {
                "index": idx,
                "text": _text_for_window(original_beats, start, end),
                "start_s": start,
                "end_s": end,
                "queries": {"visual": [], "visual_type": "broll", "theme": vibe, "keywords": []},
            }
        )

    await job_service.save_beats(session, job_id, new_beats)
    await job_service.clear_assignments(session, job_id)

    for idx, ordered in enumerate(ordered_by_beat):
        primary = ordered[0]
        await job_service.save_assignment(
            session,
            job_id,
            idx,
            platform=primary["platform"],
            media_url=primary["media_url"],
            kind=primary.get("kind") or "video",
            score=1.0,
            attribution=primary.get("attribution"),
            preview_url=primary.get("preview_url"),
            candidates=[_candidate(c, selected=(j == 0)) for j, c in enumerate(ordered)],
        )

    logger.info(
        "job %s vibe '%s': %s beats over %.1fs (%s clips per beat)",
        job_id,
        vibe,
        len(windows),
        total,
        _PER_BEAT,
    )
    await job_service.advance(session, job_id, "ready", progress="ready")
    return "ready"
