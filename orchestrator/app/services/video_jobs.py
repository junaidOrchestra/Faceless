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

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Beat, BeatAssignment, VideoJob

# active stage status -> the pending status it should reset to on restart.
ORPHAN_RESETS: dict[str, str] = {
    "transcribing": "queued",
    "llm": "transcribed",
    "rendering": "render_queued",
}

# Statuses that count as "in flight" for per-user concurrency limits: a job that
# is still consuming (or queued to consume) pipeline compute. Terminal states
# (``done``/``failed``) and the idle ``ready`` state (awaiting a user render
# request) are excluded so the limit caps active work, not parked projects.
ACTIVE_STATUSES: tuple[str, ...] = (
    "queued",
    "transcribing",
    "transcribed",
    "llm",
    "awaiting_clip",
    "render_queued",
    "rendering",
)


@dataclass(slots=True)
class RenderBeatRow:
    """Minimal beat + selected assignment fields needed by the renderer."""

    index: int
    text: str
    start_s: float
    end_s: float
    platform: str | None
    media_url: str | None
    kind: str | None


@dataclass(slots=True)
class StaleSweepResult:
    """Jobs recovered by the stale-job sweeper."""

    requeued: dict[str, list[str]]
    failed: list[str]


async def create_video_job(
    session: AsyncSession,
    job_id: str,
    user_id: str,
    audio_path: str,
    payload: dict[str, Any],
    *,
    owner_id: str | None = None,
    project_id: str | None = None,
) -> VideoJob:
    existing = await session.get(VideoJob, job_id)
    if existing:
        return existing
    job = VideoJob(
        id=job_id,
        user_id=user_id,
        owner_id=owner_id or user_id,
        project_id=project_id,
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
    now = datetime.now(timezone.utc)
    job.status = to_status
    job.claimed_at = now
    job.heartbeat_at = now
    job.attempt_count = (job.attempt_count or 0) + 1
    await session.commit()
    await session.refresh(job)
    return job


async def advance(
    session: AsyncSession, job_id: str, status: str, *, progress: str | None = None
) -> None:
    """Move a job to ``status`` (optionally updating ``progress``)."""

    values: dict[str, Any] = {
        "status": status,
        "claimed_at": None,
        "heartbeat_at": None,
    }
    if progress is not None:
        values["progress"] = progress
    await session.execute(update(VideoJob).where(VideoJob.id == job_id).values(**values))
    await session.commit()


async def try_advance(
    session: AsyncSession,
    job_id: str,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    progress: str | None = None,
) -> bool:
    """Atomically move a job ``from_statuses`` -> ``to_status``.

    Returns ``True`` only for the request that actually performed the
    transition. Concurrent or duplicate callers see the row already out of
    ``from_statuses`` and get ``False`` — they must not re-enqueue, which is what
    makes enqueue idempotent under racing requests. Unlike
    :func:`claim_for_stage` this targets *pending* statuses, so it leaves the
    claim / heartbeat / attempt bookkeeping untouched.
    """

    values: dict[str, Any] = {
        "status": to_status,
        "claimed_at": None,
        "heartbeat_at": None,
    }
    if progress is not None:
        values["progress"] = progress
    result = await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id, VideoJob.status.in_(from_statuses))
        .values(**values)
    )
    await session.commit()
    return bool(result.rowcount)


async def set_progress(session: AsyncSession, job_id: str, progress: str) -> None:
    await session.execute(
        update(VideoJob).where(VideoJob.id == job_id).values(progress=progress)
    )
    await session.commit()


async def get_progress_map(
    session: AsyncSession, job_ids: list[str]
) -> dict[str, tuple[str | None, str | None]]:
    """Map each job id -> (progress, error) in one query (for project lists)."""

    if not job_ids:
        return {}
    result = await session.execute(
        select(VideoJob.id, VideoJob.progress, VideoJob.error).where(
            VideoJob.id.in_(job_ids)
        )
    )
    return {row.id: (row.progress, row.error) for row in result.all()}


async def update_payload(
    session: AsyncSession, job_id: str, payload: dict[str, Any]
) -> None:
    """Replace a job's payload JSON (used by /prepare to record output choices)."""

    await session.execute(
        update(VideoJob).where(VideoJob.id == job_id).values(payload=payload)
    )
    await session.commit()


async def mark_done(session: AsyncSession, job_id: str, result_url: str) -> None:
    await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id)
        .values(
            status="done",
            result_url=result_url,
            error=None,
            claimed_at=None,
            heartbeat_at=None,
        )
    )
    await session.commit()


async def mark_failed(session: AsyncSession, job_id: str, error: str) -> None:
    await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id)
        .values(status="failed", error=error, claimed_at=None, heartbeat_at=None)
    )
    await session.commit()


async def get_video_job(session: AsyncSession, job_id: str) -> VideoJob | None:
    return await session.get(VideoJob, job_id)


async def get_owned_video_job(
    session: AsyncSession, job_id: str, owner_id: str
) -> VideoJob | None:
    """Return the job only if it belongs to ``owner_id`` (else ``None``).

    Ownership is enforced here so callers can answer 404 (not 403) for a job that
    exists but isn't the caller's — never leaking the existence of other users'
    jobs. Legacy rows with a NULL ``owner_id`` are treated as not owned by anyone.
    """

    job = await session.get(VideoJob, job_id)
    if job is None or job.owner_id != owner_id:
        return None
    return job


async def count_active_jobs(session: AsyncSession, owner_id: str) -> int:
    """Count the owner's jobs currently in an active (in-flight) status."""

    result = await session.execute(
        select(func.count())
        .select_from(VideoJob)
        .where(
            VideoJob.owner_id == owner_id,
            VideoJob.status.in_(ACTIVE_STATUSES),
        )
    )
    return int(result.scalar_one())


async def delete_job_cascade(session: AsyncSession, job_id: str) -> None:
    """Delete a job and its derived rows (beats + assignments).

    Used when a user deletes a project. Storage cleanup (B2/local files) is the
    caller's responsibility.
    """

    await session.execute(
        delete(BeatAssignment).where(BeatAssignment.video_job_id == job_id)
    )
    await session.execute(delete(Beat).where(Beat.video_job_id == job_id))
    await session.execute(delete(VideoJob).where(VideoJob.id == job_id))
    await session.commit()


async def get_job_duration_seconds(session: AsyncSession, job_id: str) -> float:
    """Return the job's video length (max beat end time), or 0 if no beats yet."""

    result = await session.execute(
        select(func.max(Beat.end_s)).where(Beat.video_job_id == job_id)
    )
    value = result.scalar_one_or_none()
    return float(value) if value is not None else 0.0


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
            update(VideoJob)
            .where(VideoJob.status == active)
            .values(status=pending, claimed_at=None, heartbeat_at=None)
        )
        counts[active] = result.rowcount or 0
    await session.commit()
    return counts


async def heartbeat_job(session: AsyncSession, job_id: str, active_status: str) -> bool:
    """Refresh the heartbeat for a job still in the expected active status."""

    result = await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id, VideoJob.status == active_status)
        .values(heartbeat_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return bool(result.rowcount)


async def sweep_stale_active_jobs(
    session: AsyncSession,
    *,
    stale_timeout_s: float,
    max_attempts: int,
) -> StaleSweepResult:
    """Recover active jobs whose worker heartbeat stopped.

    Alive workers refresh ``heartbeat_at`` periodically. If that timestamp stops
    moving for longer than ``stale_timeout_s`` the process likely died or got
    wedged, so the job is either requeued for its pending stage or failed once it
    has exhausted ``max_attempts``.
    """

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_timeout_s)
    requeued: dict[str, list[str]] = {pending: [] for pending in ORPHAN_RESETS.values()}
    failed: list[str] = []

    for active, pending in ORPHAN_RESETS.items():
        result = await session.execute(
            select(VideoJob.id, VideoJob.attempt_count)
            .where(
                VideoJob.status == active,
                or_(
                    VideoJob.heartbeat_at < cutoff,
                    and_(VideoJob.heartbeat_at.is_(None), VideoJob.claimed_at < cutoff),
                ),
            )
            .order_by(VideoJob.created_at)
        )
        rows = result.all()
        for job_id, attempt_count in rows:
            attempts = int(attempt_count or 0)
            if attempts >= max_attempts:
                await session.execute(
                    update(VideoJob)
                    .where(VideoJob.id == job_id, VideoJob.status == active)
                    .values(
                        status="failed",
                        error=(
                            f"{active} worker heartbeat stale after {attempts} "
                            f"attempt(s); max attempts exceeded"
                        ),
                        claimed_at=None,
                        heartbeat_at=None,
                    )
                )
                failed.append(job_id)
            else:
                update_result = await session.execute(
                    update(VideoJob)
                    .where(VideoJob.id == job_id, VideoJob.status == active)
                    .values(status=pending, claimed_at=None, heartbeat_at=None)
                )
                if update_result.rowcount:
                    requeued[pending].append(job_id)

    await session.commit()
    return StaleSweepResult(requeued=requeued, failed=failed)


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


async def apply_candidate_overrides(
    session: AsyncSession, job_id: str, overrides: dict[int, int]
) -> int:
    """Repoint beat assignments to user-picked candidates before a render.

    ``overrides`` maps ``beat_index -> candidate_index``. For each entry we copy
    the chosen candidate's media onto the assignment's scalar columns (the fields
    the renderer actually reads in ``stage_render``) and flip the ``selected``
    flag inside the stored ``candidates`` list so a later GET /beats reflects the
    pick. Idempotent: applying the same map twice is a no-op.

    Invalid entries (unknown beat, no stored candidates, out-of-range index, or a
    candidate without a ``media_url``) are skipped so one bad index can't fail the
    whole render. Returns the number of assignments actually changed.
    """

    if not overrides:
        return 0

    result = await session.execute(
        select(BeatAssignment).where(BeatAssignment.video_job_id == job_id)
    )
    by_index = {a.beat_index: a for a in result.scalars()}

    changed = 0
    for beat_index, candidate_index in overrides.items():
        assignment = by_index.get(beat_index)
        if assignment is None:
            continue
        candidates = list(assignment.candidates or [])
        if not (0 <= candidate_index < len(candidates)):
            continue
        chosen = candidates[candidate_index]
        media_url = chosen.get("media_url")
        if not media_url:
            # A candidate with no streamable media can't drive a render segment.
            continue

        # Repoint the columns the renderer reads to the chosen candidate.
        assignment.platform = chosen.get("platform")
        assignment.media_url = media_url
        assignment.preview_url = chosen.get("preview_url")
        assignment.kind = chosen.get("kind")
        assignment.score = chosen.get("score")
        assignment.attribution = chosen.get("attribution")
        # Rebuild candidates as a NEW list (so SQLAlchemy detects the JSONB
        # change) with the selected flag moved to the chosen option.
        assignment.candidates = [
            {**c, "selected": i == candidate_index} for i, c in enumerate(candidates)
        ]
        changed += 1

    if changed:
        await session.commit()
    return changed


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


async def get_render_beats(session: AsyncSession, job_id: str) -> list[RenderBeatRow]:
    """Return only the columns needed for final rendering.

    Unlike ``get_beats_with_assignments``, this intentionally avoids loading the
    assignment ``candidates`` JSONB array. Rendering only needs the selected clip
    scalar columns, so this keeps peak memory lower for long jobs with alternates.
    """

    result = await session.execute(
        select(
            Beat.index,
            Beat.text,
            Beat.start_s,
            Beat.end_s,
            BeatAssignment.platform,
            BeatAssignment.media_url,
            BeatAssignment.kind,
        )
        .outerjoin(
            BeatAssignment,
            and_(
                BeatAssignment.video_job_id == Beat.video_job_id,
                BeatAssignment.beat_index == Beat.index,
            ),
        )
        .where(Beat.video_job_id == job_id)
        .order_by(Beat.index)
    )
    return [RenderBeatRow(*row) for row in result.all()]
