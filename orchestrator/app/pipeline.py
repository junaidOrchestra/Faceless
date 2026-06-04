"""End-to-end video pipeline: transcribe → LLM → CLIP → timeline → render."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .clip_client.base import ClipClient
from .clip_client.schemas import ClipJobItemResult, ClipRankedAsset
from .config import Settings
from .llm.base import LLMProvider, Vocabulary
from .renderer.base import Renderer, TimelineBeat
from .services import video_jobs as job_service
from .transcriber.base import BeatSegment, Transcriber

logger = logging.getLogger(__name__)


def _pick_keyword(plan: Any, vocabulary: Vocabulary) -> str:
    if plan.visual_queries:
        return plan.visual_queries[0]
    if vocabulary.subjects:
        return vocabulary.subjects[0]
    return vocabulary.topic or "abstract background"


def _fallback_asset(vocabulary: Vocabulary) -> ClipRankedAsset:
    subject = vocabulary.subjects[0] if vocabulary.subjects else vocabulary.topic
    return ClipRankedAsset(
        platform="fallback",
        kind="photo",
        media_url=f"https://picsum.photos/seed/{subject}/1280/720",
        preview_url=f"https://picsum.photos/seed/{subject}/640/480",
        attribution_name="Fallback",
        attribution_url=None,
        license=None,
        score=0.0,
    )


async def run_video_pipeline(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    audio_path: str,
    payload: dict[str, Any],
    *,
    transcriber: Transcriber,
    llm: LLMProvider,
    clip_client: ClipClient,
    renderer: Renderer,
) -> str:
    """Execute the full pipeline and return ``result_url``."""

    credentials = (payload.get("credentials") or {})
    sources: list[str] | None = payload.get("sources") or settings.default_sources

    await job_service.set_progress(session, job_id, "transcribing")
    segments = await transcriber.transcribe(audio_path)
    beats_payload = [
        {"index": s.index, "text": s.text, "start_s": s.start_s, "end_s": s.end_s}
        for s in segments
    ]
    transcript = " ".join(s.text for s in segments)

    await job_service.set_progress(session, job_id, "llm_vocabulary")
    vocabulary = await llm.vocabulary(transcript)

    await job_service.set_progress(session, job_id, "llm_beat_queries")
    plans = await llm.beat_queries(beats_payload, vocabulary)
    beats_with_queries: list[dict[str, Any]] = []
    for seg, plan in zip(segments, plans, strict=True):
        beats_with_queries.append(
            {
                **beats_payload[seg.index],
                "queries": {
                    "visual": plan.visual_queries,
                    "metaphor": plan.metaphor_queries,
                    "is_rhetorical": plan.is_rhetorical,
                    "text_overlay": plan.text_overlay,
                },
            }
        )
    await job_service.save_beats(session, job_id, beats_with_queries)

    clip_job_id = f"{job_id}-clip"
    clip_items = [
        {
            "ref": str(seg.index),
            "keyword": _pick_keyword(plan, vocabulary),
            "sources": sources,
        }
        for seg, plan in zip(segments, plans, strict=True)
    ]

    await job_service.set_progress(session, job_id, "clip_search")
    clip_result = await clip_client.submit_and_poll(
        clip_job_id,
        clip_items,
        credentials,
        sources,
        poll_interval_s=settings.clip_poll_interval_s,
        poll_timeout_s=settings.clip_poll_timeout_s,
    )
    if clip_result.status == "failed":
        raise RuntimeError(clip_result.error or "CLIP job failed")

    by_ref: dict[str, ClipJobItemResult] = {item.ref: item for item in clip_result.items}

    timeline: list[TimelineBeat] = []
    for seg, plan in zip(segments, plans, strict=True):
        item = by_ref.get(str(seg.index))
        asset: ClipRankedAsset | None = None
        if item and item.assets:
            asset = max(item.assets, key=lambda a: a.score)
        elif item and item.error:
            logger.warning("beat %s clip error: %s", seg.index, item.error)
        if asset is None:
            asset = _fallback_asset(vocabulary)

        await job_service.save_assignment(
            session,
            job_id,
            seg.index,
            platform=asset.platform,
            media_url=asset.media_url,
            kind=asset.kind,
            score=asset.score,
            attribution=asset.attribution_name,
        )

        if plan.is_rhetorical:
            timeline.append(
                TimelineBeat(
                    seg.start_s,
                    seg.end_s,
                    kind="text",
                    media_url=None,
                    text_overlay=plan.text_overlay or seg.text,
                    is_rhetorical=True,
                )
            )
        else:
            timeline.append(
                TimelineBeat(
                    seg.start_s,
                    seg.end_s,
                    kind=asset.kind,
                    media_url=asset.media_url,
                    text_overlay=plan.text_overlay,
                )
            )

    await job_service.set_progress(session, job_id, "rendering")
    out_dir = Path(settings.render_temp_dir) / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"{job_id}.mp4")
    await renderer.render(audio_path, timeline, output_path)

    result_url = f"{settings.result_base_url.rstrip('/')}/{job_id}.mp4"
    return result_url
