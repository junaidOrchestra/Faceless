"""Job persistence helpers — idempotent upsert, status transitions, pruning."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Job

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StaleSweepResult:
    requeued: list[str]
    failed: list[str]


async def upsert_job(
    session: AsyncSession,
    job_id: str,
    items_input: dict[str, Any],
) -> Job:
    """Create a queued job or return the existing row (idempotent on ``job_id``)."""

    existing = await session.get(Job, job_id)
    if existing is not None:
        return existing

    job = Job(job_id=job_id, status="queued", items_input=items_input)
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        # Two submits for a brand-new job_id raced between the get() above and
        # this commit; the unique PK rejects the loser. Idempotent: roll back and
        # return the row that won so the caller still sees a single queued job.
        await session.rollback()
        existing = await session.get(Job, job_id)
        if existing is not None:
            return existing
        raise
    await session.refresh(job)
    return job


async def claim_next_job(session: AsyncSession, _timeout_s: float) -> Job | None:
    """Claim the oldest ``queued`` job and record a new running attempt."""

    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.claimed_at = now
    job.heartbeat_at = now
    job.attempt_count = (job.attempt_count or 0) + 1
    await session.commit()
    await session.refresh(job)
    return job


async def mark_job_done(
    session: AsyncSession,
    job_id: str,
    items_result: list[dict[str, Any]],
) -> None:
    await session.execute(
        update(Job)
        .where(Job.job_id == job_id)
        .values(
            status="done",
            items_result=items_result,
            error=None,
            claimed_at=None,
            heartbeat_at=None,
        )
    )
    await session.commit()


async def mark_job_failed(session: AsyncSession, job_id: str, error: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.job_id == job_id)
        .values(status="failed", error=error, claimed_at=None, heartbeat_at=None)
    )
    await session.commit()


async def heartbeat_job(session: AsyncSession, job_id: str) -> bool:
    """Refresh the heartbeat for a job that is still running."""

    result = await session.execute(
        update(Job)
        .where(Job.job_id == job_id, Job.status == "running")
        .values(heartbeat_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return bool(result.rowcount)


async def sweep_stale_jobs(
    session: AsyncSession,
    *,
    stale_timeout_s: float,
    max_attempts: int,
) -> StaleSweepResult:
    """Requeue or fail running jobs whose worker heartbeat stopped."""

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_timeout_s)
    result = await session.execute(
        select(Job.job_id, Job.attempt_count)
        .where(
            Job.status == "running",
            Job.claimed_at.is_not(None),
            (Job.heartbeat_at < cutoff)
            | ((Job.heartbeat_at.is_(None)) & (Job.claimed_at < cutoff)),
        )
        .order_by(Job.created_at)
    )
    requeued: list[str] = []
    failed: list[str] = []
    for job_id, attempt_count in result.all():
        attempts = int(attempt_count or 0)
        if attempts >= max_attempts:
            update_result = await session.execute(
                update(Job)
                .where(Job.job_id == job_id, Job.status == "running")
                .values(
                    status="failed",
                    error=(
                        f"clip worker heartbeat stale after {attempts} "
                        f"attempt(s); max attempts exceeded"
                    ),
                    claimed_at=None,
                    heartbeat_at=None,
                )
            )
            if update_result.rowcount:
                failed.append(job_id)
        else:
            update_result = await session.execute(
                update(Job)
                .where(Job.job_id == job_id, Job.status == "running")
                .values(status="queued", claimed_at=None, heartbeat_at=None)
            )
            if update_result.rowcount:
                requeued.append(job_id)

    await session.commit()
    return StaleSweepResult(requeued=requeued, failed=failed)


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    return await session.get(Job, job_id)


async def prune_job(session: AsyncSession, job_id: str) -> None:
    await session.execute(delete(Job).where(Job.job_id == job_id))
    await session.commit()


async def prune_expired_jobs(session: AsyncSession, ttl_s: float) -> int:
    """Delete terminal jobs older than ``ttl_s`` (safety net if clients never fetch)."""

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_s)
    result = await session.execute(
        delete(Job).where(
            Job.status.in_(("done", "failed")),
            Job.updated_at < cutoff,
        )
    )
    await session.commit()
    return result.rowcount or 0
