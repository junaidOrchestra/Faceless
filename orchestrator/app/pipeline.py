"""Staged video pipeline.

The end-to-end flow (transcribe -> LLM -> CLIP search -> render) is split into
independent stage functions so a dedicated worker can run each one and hand the
job to the next stage via Redis. Inter-stage data lives in Postgres: the
``beats`` table carries transcript/timing/queries, and ``beat_assignments``
carries the media chosen per beat. Each stage therefore reconstructs its inputs
from the DB, which makes restarts recoverable.

Stages:

* :func:`stage_transcribe` — audio -> beats (text/timing) saved to ``beats``.
* :func:`stage_llm`        — beats -> vocabulary + per-beat queries; submit the
  CLIP search job (fire-and-forget). Returns whether a clip job is in flight.
* :func:`poll_clip_job`    — poll the CLIP job once; on completion select one
  unique asset per beat and write ``beat_assignments``.
* :func:`stage_render`     — beats + assignments -> gapless timeline -> MP4.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import storage
from . import vibe_pipeline
from . import vibes as vibe_registry
from .clip_client.base import ClipClient
from .clip_client.schemas import ClipRankedAsset
from .config import Settings
from .formats import search_orientation
from .llm.base import LLMProvider, Vocabulary
from .renderer.base import Renderer, TimelineBeat
from .services import video_jobs as job_service
from .transcriber.base import BeatSegment, Transcriber

logger = logging.getLogger(__name__)


def _clip_keywords(plan: Any, vocabulary: Vocabulary, *, limit: int = 3) -> list[str]:
    """Return several stock-search keywords for one beat.

    Use the beat's OWN visual/metaphor queries (up to ``limit``). The global
    vocabulary (shared subjects/topic) is only a LAST RESORT for a beat the model
    left empty — never a top-up. Appending a shared subject to beats that already
    had queries made the same asset (e.g. a "log cabin") surface as a candidate on
    nearly every beat and polluted the whole video.
    """

    out: list[str] = []
    seen: set[str] = set()
    for keyword in [*getattr(plan, "visual_queries", []), *getattr(plan, "metaphor_queries", [])]:
        cleaned = " ".join(str(keyword).split()).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
        if len(out) >= limit:
            return out

    # The beat produced at least one query of its own: keep it tight and on-topic.
    if out:
        return out

    # Empty beat only: fall back to a single shared vocabulary phrase.
    for keyword in [*vocabulary.subjects, vocabulary.topic or "abstract background"]:
        cleaned = " ".join(str(keyword).split()).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            return [cleaned]
    return ["abstract background"]


def _ref_beat(ref: str) -> int:
    """Beat index encoded in a clip ref (``"<beat>:<query>"``)."""

    try:
        return int(ref.split(":", 1)[0])
    except (ValueError, IndexError):
        return -1


def _probe_audio_duration(audio_path: str) -> float | None:
    """Return audio duration in seconds via ffprobe, or ``None`` on failure."""

    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as exc:
        logger.warning("ffprobe failed for %s: %s", audio_path, exc)
        return None


def _clip_boundaries(
    segments: list[BeatSegment], audio_duration_s: float | None
) -> list[float]:
    """Return ``len(segments)+1`` monotonic boundaries covering ``[0, audio_end]``.

    The renderer concatenates clips back-to-back, so a clip's *duration* is what
    decides how long an image stays on screen. To keep visuals in sync with the
    narration and make the rendered length equal the audio length, the timeline
    is GAPLESS: each image shows from its own beat's start until the NEXT beat
    begins (absorbing inter-beat silence), and the last clip runs to the end of
    the audio (covering lead-out silence). Mirrors faceless_lazy step5.
    """

    if not segments:
        return [0.0, audio_duration_s or 3.0]

    boundaries: list[float] = [0.0]
    for seg in segments[1:]:
        boundaries.append(float(seg.start_s))

    last_end = audio_duration_s if audio_duration_s else segments[-1].end_s
    boundaries.append(max(float(last_end), float(segments[-1].end_s)))

    for i in range(1, len(boundaries)):
        if boundaries[i] < boundaries[i - 1]:
            boundaries[i] = boundaries[i - 1]
    return boundaries


def _asset_to_candidate(asset: ClipRankedAsset, *, selected: bool) -> dict[str, Any]:
    """Flatten a ranked asset into the candidate dict stored on the assignment."""

    return {
        "platform": asset.platform,
        "kind": asset.kind,
        "media_url": asset.media_url,
        "preview_url": asset.preview_url,
        "score": asset.score,
        "attribution": asset.attribution_name,
        "selected": selected,
    }


def _pick_unique_asset(
    assets: list[ClipRankedAsset], used_urls: set[str]
) -> ClipRankedAsset | None:
    """Pick the highest-scoring asset NOT already used elsewhere in the video.

    Hard no-repeat rule: any asset already shown in an earlier beat is excluded
    entirely. Returns ``None`` when every candidate for this beat has already been
    used (the caller then renders a text card) so no image ever appears twice.
    """

    fresh = [a for a in assets if a.media_url not in used_urls]
    if not fresh:
        return None
    best = max(fresh, key=lambda a: a.score)
    used_urls.add(best.media_url)
    return best


# ---------------------------------------------------------------------------
# Stage 1: transcribe
# ---------------------------------------------------------------------------


async def stage_transcribe(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    audio_path: str,
    payload: dict[str, Any],
    *,
    transcriber: Transcriber,
) -> None:
    """Transcribe audio into beats and persist them (text/timing only)."""

    await job_service.set_progress(session, job_id, "transcribing")
    # Recover the narration from durable storage if an ephemeral-/tmp restart
    # dropped it between submit and this worker picking the job up.
    audio_path = await storage.ensure_local_audio(
        settings, audio_path, payload.get("audio_object")
    )
    segments = await transcriber.transcribe(audio_path)
    beats = [
        {"index": s.index, "text": s.text, "start_s": s.start_s, "end_s": s.end_s}
        for s in segments
    ]
    await job_service.save_beats(session, job_id, beats)
    logger.info("job %s transcribed into %s beats", job_id, len(beats))


# ---------------------------------------------------------------------------
# Stage 2: LLM (vocabulary + per-beat queries) + submit clip search
# ---------------------------------------------------------------------------


async def stage_llm(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    payload: dict[str, Any],
    *,
    llm: LLMProvider,
    clip_client: ClipClient,
) -> bool:
    """Run the LLM, persist per-beat queries, and submit the CLIP search job.

    Returns ``True`` when a CLIP job was submitted (the job should move to
    ``awaiting_clip``), or ``False`` when there is nothing to search (no beats /
    no keywords) so the job can go straight to ``ready``.
    """

    credentials = payload.get("credentials") or {}
    sources: list[str] | None = payload.get("sources") or settings.default_sources
    fmt = payload.get("format") or {}
    orientation: str | None = search_orientation(fmt.get("orientation"))
    quality: str | None = payload.get("quality")

    beats = await job_service.get_beats(session, job_id)
    if not beats:
        return False

    # Vibe mode: the user chose a visual theme instead of "match my script". Skip
    # the transcript-driven vocabulary + visual director entirely and hand off to
    # the separate vibe pipeline, which fetches an UNRANKED pool of theme clips
    # (tiled by duration into beats once the search completes).
    theme = payload.get("theme") or {}
    if str(theme.get("mode") or "script").lower() == "vibe" and vibe_registry.is_vibe(
        theme.get("vibe")
    ):
        return await vibe_pipeline.submit_vibe_pool(
            session,
            settings,
            job_id,
            payload,
            beats,
            str(theme.get("vibe")),
            llm=llm,
            clip_client=clip_client,
        )

    beats_payload = [
        {"index": b.index, "text": b.text, "start_s": b.start_s, "end_s": b.end_s}
        for b in beats
    ]
    transcript = " ".join(b.text for b in beats)

    await job_service.set_progress(session, job_id, "llm_vocabulary")
    vocabulary = await llm.vocabulary(transcript)

    await job_service.set_progress(session, job_id, "llm_beat_queries")
    plans = await llm.beat_queries(beats_payload, vocabulary)

    # Persist the searchable queries chosen per beat (for GET /beats) and build
    # the CLIP item list. Refs encode the beat index ("<beat>:<query>") so the
    # poller can group results back to beats without extra bookkeeping.
    #
    # Long narrations (many beats) × 3 queries/beat can exceed the clip-server's
    # per-job item cap. Scale keywords-per-beat down to fit the budget so a long
    # video degrades gracefully (fewer queries each) instead of failing the whole
    # submit with a 400 — typical lengths still get the full 3 queries/beat.
    max_items = max(1, settings.clip_max_items_per_job)
    per_beat_limit = max(1, min(3, max_items // len(beats)))

    # Per-beat source routing: beats the visual director classifies as a real
    # named "person" or a specific named "event" want authentic photographs (route
    # to Openverse/Pexels, configurable), while everything else keeps the default
    # stock sources (Pexels). Routing is per-beat, so within one transcript some
    # beats hit pexels_video and named person/event beats hit Openverse. Each list
    # falls back to the default sources if left empty.
    person_sources: list[str] | None = settings.person_sources or sources
    event_sources: list[str] | None = settings.event_sources or sources
    routed_sources = {"person": person_sources, "event": event_sources}

    beats_with_queries: list[dict[str, Any]] = []
    clip_items: list[dict[str, Any]] = []
    for b, plan in zip(beats, plans, strict=True):
        keywords = _clip_keywords(plan, vocabulary, limit=per_beat_limit)
        item_sources = routed_sources.get(plan.visual_type, sources)
        beats_with_queries.append(
            {
                "index": b.index,
                "text": b.text,
                "start_s": b.start_s,
                "end_s": b.end_s,
                "queries": {
                    "visual": plan.visual_queries,
                    "metaphor": plan.metaphor_queries,
                    "visual_type": plan.visual_type,
                    "spec": plan.spec,
                    "prefers_video": plan.prefers_video,
                    "keywords": keywords,
                },
            }
        )
        for q_index, keyword in enumerate(keywords):
            clip_items.append(
                {"ref": f"{b.index}:{q_index}", "keyword": keyword, "sources": item_sources}
            )

    await job_service.save_beats(session, job_id, beats_with_queries)

    if not clip_items:
        return False

    # Final guard for pathologically long narrations (more beats than the cap):
    # trim the tail so the submit never 400s. Trailing beats fall back to text.
    if len(clip_items) > max_items:
        logger.warning(
            "job %s: %s clip items exceeds cap %s; truncating",
            job_id,
            len(clip_items),
            max_items,
        )
        clip_items = clip_items[:max_items]

    # The CLIP job id is derived from job_id, so a re-run after a restart
    # reconnects to the same job via the clip-server's idempotent submit.
    await job_service.set_progress(session, job_id, "clip_submit")
    await clip_client.submit(
        f"{job_id}-clip",
        clip_items,
        credentials,
        sources,
        orientation=orientation,
        quality=quality,
    )
    return True


# ---------------------------------------------------------------------------
# Stage 3: poll the CLIP job and select assets
# ---------------------------------------------------------------------------


async def poll_clip_job(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    payload: dict[str, Any],
    *,
    clip_client: ClipClient,
) -> str:
    """Poll the CLIP job once.

    Returns ``"pending"`` (still searching), ``"failed"`` (marked failed), or
    ``"ready"`` (assignments written, job ready to render).
    """

    status = await clip_client.poll(f"{job_id}-clip")
    if status.status == "failed":
        await job_service.mark_failed(session, job_id, status.error or "CLIP job failed")
        return "failed"
    if status.status != "done":
        # queued / running / processing — still searching.
        return "pending"

    # Vibe mode: hand the finished (unranked) pool to the separate vibe pipeline,
    # which tiles the clips by duration into beats. Keeps the script assembly
    # below fully isolated from the vibe path.
    theme = payload.get("theme") or {}
    if str(theme.get("mode") or "script").lower() == "vibe" and vibe_registry.is_vibe(
        theme.get("vibe")
    ):
        return await vibe_pipeline.assemble_vibe_timeline(
            session, job_id, str(theme.get("vibe")), status
        )

    by_ref = {item.ref: item for item in status.items}
    beats = await job_service.get_beats(session, job_id)

    # If the narration came from a user video, that footage is offered as a
    # swappable alternate on every beat — but the DEFAULT (rendered) pick is the
    # best-ranked stock match for the beat's text. The user's footage only
    # becomes the default when no stock asset matched the beat (it always covers
    # the beat, so there is still no text fallback in this mode). See below.
    source_video_url = (payload.get("source_video") or {}).get("url")

    # Re-run safety: clear any assignments from a previous (interrupted) poll.
    await job_service.clear_assignments(session, job_id)

    # Hard "no image twice" rule, plus deliberate motif reuse: beats that share an
    # identical primary query reuse the SAME asset instead of forcing a unique
    # pick (which would otherwise drop to a text card).
    used_urls: set[str] = set()
    motif_assets: dict[str, ClipRankedAsset] = {}
    visual_beats = 0
    fallback_beats = 0

    for b in beats:
        queries = b.queries or {}
        vis = queries.get("visual") or []
        motif_key = (vis[0].strip().lower() or None) if vis else None

        # Pool every ranked asset for this beat (best score per distinct media_url),
        # high-to-low. The top is the default; the rest are alternates for the UI.
        items = [by_ref[r] for r in by_ref if _ref_beat(r) == b.index]
        assets_by_url: dict[str, ClipRankedAsset] = {}
        for item in items:
            for candidate in item.assets:
                current = assets_by_url.get(candidate.media_url)
                if current is None or candidate.score > current.score:
                    assets_by_url[candidate.media_url] = candidate
        pool = sorted(assets_by_url.values(), key=lambda a: a.score, reverse=True)

        # Default (rendered) asset: reuse a shared motif pick, else best unused.
        asset: ClipRankedAsset | None = None
        if motif_key and motif_key in motif_assets:
            asset = motif_assets[motif_key]
        if asset is None and pool:
            asset = _pick_unique_asset(pool, used_urls)
            if asset is not None and motif_key and asset.platform != "fallback":
                motif_assets[motif_key] = asset
        if asset is None and not pool:
            errors = [item.error for item in items if item.error]
            if errors:
                logger.warning("beat %s clip errors: %s", b.index, "; ".join(errors))

        # Stock alternates for this beat, best-scoring first. Marked unselected
        # for now; the default is chosen below (user video if present, else the
        # top stock pick). Up to three so the picker shows a few options.
        stock_candidates: list[dict[str, Any]] = []
        if asset is not None:
            stock_candidates.append(_asset_to_candidate(asset, selected=False))
            for alt in pool:
                if len(stock_candidates) >= 3:
                    break
                if alt.media_url == asset.media_url:
                    continue
                stock_candidates.append(_asset_to_candidate(alt, selected=False))

        if source_video_url:
            # The user's footage is always an available candidate, but it is no
            # longer auto-selected: the best-ranked stock match leads. The user
            # video is sliced to this beat's window at render time (the renderer
            # seeks to beat.start_s) only if the user picks it.
            user_candidate = {
                "platform": "user_video",
                "kind": "video",
                "media_url": source_video_url,
                "preview_url": source_video_url,
                "score": 1.0,
                "attribution": "Your footage",
                "selected": False,
            }
            if asset is not None:
                # Stock best match is the default; user footage trails as an
                # alternate the user can switch to.
                candidates = [
                    {**stock_candidates[0], "selected": True},
                    *stock_candidates[1:],
                    user_candidate,
                ][:4]
                await job_service.save_assignment(
                    session,
                    job_id,
                    b.index,
                    platform=asset.platform,
                    media_url=asset.media_url,
                    kind=asset.kind,
                    score=asset.score,
                    attribution=asset.attribution_name,
                    preview_url=asset.preview_url,
                    candidates=candidates,
                )
            else:
                # No stock match for this beat — fall back to the user's footage
                # as the default (better than a text card when we have footage).
                user_candidate["selected"] = True
                await job_service.save_assignment(
                    session,
                    job_id,
                    b.index,
                    platform="user_video",
                    media_url=source_video_url,
                    kind="video",
                    score=1.0,
                    attribution="Your footage",
                    preview_url=source_video_url,
                    candidates=[user_candidate, *stock_candidates][:4],
                )
            visual_beats += 1
            continue

        if asset is None:
            # No candidates, or all already used earlier — the only place text is
            # allowed in the video.
            await job_service.save_assignment(
                session,
                job_id,
                b.index,
                platform="generated",
                media_url=None,
                kind="text",
                score=None,
                attribution="no_asset_fallback",
                preview_url=None,
                candidates=[],
            )
            visual_beats += 1
            fallback_beats += 1
            continue

        # Stock default: promote the top pick to selected, keep the rest as
        # alternates (each with preview_url + media_url for the UI).
        candidates = [{**stock_candidates[0], "selected": True}, *stock_candidates[1:]]

        await job_service.save_assignment(
            session,
            job_id,
            b.index,
            platform=asset.platform,
            media_url=asset.media_url,
            kind=asset.kind,
            score=asset.score,
            attribution=asset.attribution_name,
            preview_url=asset.preview_url,
            candidates=candidates,
        )
        visual_beats += 1
        if asset.platform == "fallback":
            fallback_beats += 1

    # Guard: if most beats fell back to text, no media source returned usable
    # results (e.g. a key-required source requested without its key). Fail loudly
    # rather than producing a mostly text-only video.
    if visual_beats:
        ratio = fallback_beats / visual_beats
        if ratio > settings.max_fallback_ratio:
            sources = payload.get("sources") or settings.default_sources
            await job_service.mark_failed(
                session,
                job_id,
                f"{fallback_beats}/{visual_beats} beats fell back to text cards "
                f"({ratio:.0%} > {settings.max_fallback_ratio:.0%}). No media source "
                f"returned usable results for sources={sources}. Check sources are "
                f"enabled on the clip-server and required API keys were provided.",
            )
            return "failed"

    # Prepared: beats + assignments are persisted; rendering is on demand.
    await job_service.advance(session, job_id, "ready", progress="ready")
    return "ready"


# ---------------------------------------------------------------------------
# Stage 4: render (on demand via API)
# ---------------------------------------------------------------------------


async def stage_render(
    session: AsyncSession,
    settings: Settings,
    job_id: str,
    audio_path: str,
    payload: dict[str, Any],
    *,
    renderer: Renderer,
) -> str:
    """Build the gapless timeline from stored beats/assignments and render the MP4."""

    fmt = payload.get("format") or {}
    out_width = int(fmt.get("width") or 1920)
    out_height = int(fmt.get("height") or 1080)

    render_rows = await job_service.get_render_beats(session, job_id)
    if not render_rows:
        raise RuntimeError("No beats to render — run the earlier stages first.")

    # Render is on-demand and may run after a restart that wiped ephemeral /tmp,
    # so make sure the narration is present locally (re-fetch from B2 if needed)
    # before ffprobe/ffmpeg touch it.
    audio_path = await storage.ensure_local_audio(
        settings, audio_path, payload.get("audio_object")
    )

    segments = [
        BeatSegment(index=b.index, text=b.text, start_s=b.start_s, end_s=b.end_s)
        for b in render_rows
    ]
    audio_duration_s = await asyncio.to_thread(_probe_audio_duration, audio_path)
    boundaries = _clip_boundaries(segments, audio_duration_s)
    logger.info(
        "timeline: %s beats, audio=%.2fs, last boundary=%.2fs",
        len(segments),
        audio_duration_s or -1.0,
        boundaries[-1],
    )

    show_subs = bool(payload.get("subtitles"))
    timeline: list[TimelineBeat] = []
    for i, beat in enumerate(render_rows):
        clip_start = boundaries[i]
        clip_end = boundaries[i + 1]
        if beat.media_url:
            # For the user's own video, the media_url is the whole uploaded clip;
            # seek into it at this beat's narration start so each beat shows the
            # matching slice (the source's audio == the narration, so beat.start_s
            # is the correct in-point). Stock clips have no in-point (start at 0).
            is_user_video = (beat.platform or "").lower() == "user_video"
            timeline.append(
                TimelineBeat(
                    clip_start,
                    clip_end,
                    kind=beat.kind or "photo",
                    # Burn the beat's narration as a bottom caption when subtitles
                    # are requested; the renderer draws it during the per-segment
                    # encode it already runs (no extra pass).
                    media_url=beat.media_url,
                    text_overlay=beat.text if show_subs else None,
                    source_in_s=float(beat.start_s) if is_user_video else None,
                )
            )
        else:
            timeline.append(
                TimelineBeat(
                    clip_start,
                    clip_end,
                    kind="text",
                    media_url=None,
                    text_overlay=beat.text,
                    is_rhetorical=False,
                )
            )

    await job_service.set_progress(session, job_id, "rendering")
    # Finished video lands at the ROOT of the mounted render dir so it is easy to
    # find; the renderer keeps intermediate segments in a <job_id>/ subfolder.
    render_root = Path(settings.render_temp_dir)
    render_root.mkdir(parents=True, exist_ok=True)
    output_path = str(render_root / f"{job_id}.mp4")
    await renderer.render(
        audio_path, timeline, output_path, width=out_width, height=out_height
    )

    # Local disk or Backblaze B2 depending on settings.storage_local.
    return await storage.publish_result(settings, job_id, output_path)
