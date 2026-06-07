"""Video job persistence and stage transitions for the staged pipeline.

The job lifecycle is a state machine carried in ``video_jobs.status``:

``queued`` (transcribe pending) -> ``transcribing`` -> ``transcribed`` (llm
pending) -> ``llm`` -> ``awaiting_clip`` (poller scans) -> ``ready`` (clip done,
beats/assignments stored, awaiting a render request) -> ``render_queued`` ->
``rendering`` -> ``done``. ``failed`` is reachable from any active stage.

Each "pending" status (``queued``/``transcribed``/``render_queued``) corresponds
to a Redis queue; the active statuses (``transcribing``/``llm``/``rendering``)
are reset back to their pending status on startup so orphaned work is requeued.
``awaiting_clip`` has no queue — the single clip poller scans for it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Beat, BeatAssignment, VideoJob

# active stage status -> the pending status it should reset to on restart.
ORPHAN_RESETS: dict[str, str] = {
    "transcribing": "queued",
    "llm": "transcribed",
    "rendering": "render_queued",
}


async def create_video_job(
    session: AsyncSession,
    job_id: str,
    user_id: str,
    audio_path: str,
    payload: dict[str, Any],
) -> VideoJob:
    existing = await session.get(VideoJob, job_id)
    if existing:
        return existing
    job = VideoJob(
        id=job_id,
        user_id=user_id,
        status="queued",
        audio_path=audio_path,
        payload=payload,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def claim_for_stage(
    session: AsyncSession,
    job_id: str,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
) -> VideoJob | None:
    """Transition a job into an active stage and return it, or ``None``.

    Dispatch is owned by Redis (a job id reaches exactly one worker), so this is
    a guarded state transition rather than a contended claim: a job not in one of
    ``from_statuses`` (e.g. a duplicate queue entry, or already advanced) is a
    no-op returning ``None``.
    """

    job = await session.get(VideoJob, job_id)
    if job is None or job.status not in from_statuses:
        return None
    job.status = to_status
    await session.commit()
    await session.refresh(job)
    return job


async def advance(
    session: AsyncSession, job_id: str, status: str, *, progress: str | None = None
) -> None:
    """Move a job to ``status`` (optionally updating ``progress``)."""

    values: dict[str, Any] = {"status": status}
    if progress is not None:
        values["progress"] = progress
    await session.execute(update(VideoJob).where(VideoJob.id == job_id).values(**values))
    await session.commit()


async def set_progress(session: AsyncSession, job_id: str, progress: str) -> None:
    await session.execute(
        update(VideoJob).where(VideoJob.id == job_id).values(progress=progress)
    )
    await session.commit()


async def mark_done(session: AsyncSession, job_id: str, result_url: str) -> None:
    await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id)
        .values(status="done", result_url=result_url, error=None)
    )
    await session.commit()


async def mark_failed(session: AsyncSession, job_id: str, error: str) -> None:
    await session.execute(
        update(VideoJob).where(VideoJob.id == job_id).values(status="failed", error=error)
    )
    await session.commit()


async def get_video_job(session: AsyncSession, job_id: str) -> VideoJob | None:
    return await session.get(VideoJob, job_id)


# ---------------------------------------------------------------------------
# Startup reconciliation (one call per process start)
# ---------------------------------------------------------------------------


async def reset_orphans(session: AsyncSession) -> dict[str, int]:
    """Reset jobs stuck in an active stage back to that stage's pending status.

    A just-started orchestrator owns no in-flight work, so any job in an active
    status (``transcribing``/``llm``/``rendering``) was orphaned by a previous
    process and is requeued for its stage. ``awaiting_clip`` is left alone — the
    poller picks it up on its next scan.
    """

    counts: dict[str, int] = {}
    for active, pending in ORPHAN_RESETS.items():
        result = await session.execute(
            update(VideoJob).where(VideoJob.status == active).values(status=pending)
        )
        counts[active] = result.rowcount or 0
    await session.commit()
    return counts


async def list_job_ids_by_status(session: AsyncSession, status: str) -> list[str]:
    """Return all job ids in ``status``, oldest first (used to rebuild a queue)."""

    result = await session.execute(
        select(VideoJob.id).where(VideoJob.status == status).order_by(VideoJob.created_at)
    )
    return [row[0] for row in result.all()]


async def list_awaiting_clip_jobs(session: AsyncSession) -> list[VideoJob]:
    """Return jobs whose clip search the poller should check (oldest first)."""

    result = await session.execute(
        select(VideoJob)
        .where(VideoJob.status == "awaiting_clip")
        .order_by(VideoJob.created_at)
    )
    return list(result.scalars())


# ---------------------------------------------------------------------------
# Beats / assignments (inter-stage data store)
# ---------------------------------------------------------------------------


async def save_beats(session: AsyncSession, job_id: str, beats: list[dict[str, Any]]) -> None:
    """Persist the beat breakdown for a job (idempotent — clears any prior rows).

    A stage re-run after a restart re-saves beats, so we delete existing
    beats/assignments first to avoid primary-key collisions on the second pass.
    """

    await session.execute(delete(BeatAssignment).where(BeatAssignment.video_job_id == job_id))
    await session.execute(delete(Beat).where(Beat.video_job_id == job_id))
    for b in beats:
        session.add(
            Beat(
                video_job_id=job_id,
                index=b["index"],
                text=b["text"],
                start_s=b["start_s"],
                end_s=b["end_s"],
                queries=b.get("queries"),
            )
        )
    await session.commit()


async def clear_assignments(session: AsyncSession, job_id: str) -> None:
    """Delete a job's beat assignments (poller re-run safety)."""

    await session.execute(delete(BeatAssignment).where(BeatAssignment.video_job_id == job_id))
    await session.commit()


async def save_assignment(
    session: AsyncSession,
    job_id: str,
    beat_index: int,
    *,
    platform: str | None,
    media_url: str | None,
    kind: str | None,
    score: float | None,
    attribution: str | None,
    preview_url: str | None = None,
    candidates: list[Any] | None = None,
) -> None:
    session.add(
        BeatAssignment(
            video_job_id=job_id,
            beat_index=beat_index,
            platform=platform,
            media_url=media_url,
            preview_url=preview_url,
            kind=kind,
            score=score,
            attribution=attribution,
            candidates=candidates or [],
        )
    )
    await session.commit()


async def get_beats(session: AsyncSession, job_id: str) -> list[Beat]:
    """Return every beat of a job, ordered by index."""

    result = await session.execute(
        select(Beat).where(Beat.video_job_id == job_id).order_by(Beat.index)
    )
    return list(result.scalars())


async def get_beats_with_assignments(
    session: AsyncSession, job_id: str
) -> list[tuple[Beat, BeatAssignment | None]]:
    """Return every beat of a job (ordered) paired with its selected clip, if any."""

    beats = await get_beats(session, job_id)

    assign_result = await session.execute(
        select(BeatAssignment).where(BeatAssignment.video_job_id == job_id)
    )
    by_index = {a.beat_index: a for a in assign_result.scalars()}

    return [(beat, by_index.get(beat.index)) for beat in beats]
