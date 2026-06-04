"""Job persistence helpers — idempotent upsert, status transitions, pruning."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Job

logger = logging.getLogger(__name__)


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
    await session.commit()
    await session.refresh(job)
    return job


async def claim_next_job(session: AsyncSession, timeout_s: float) -> Job | None:
    """Atomically claim the oldest ``queued`` job, or re-queue a stuck ``running`` one."""

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=timeout_s)

    # Re-queue jobs whose worker died mid-flight (claimed_at older than timeout).
    await session.execute(
        update(Job)
        .where(Job.status == "running", Job.claimed_at.is_not(None), Job.claimed_at < cutoff)
        .values(status="queued", claimed_at=None)
    )
    await session.commit()

    result = await session.execute(
        select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.claimed_at = now
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
        .values(status="done", items_result=items_result, error=None, claimed_at=None)
    )
    await session.commit()


async def mark_job_failed(session: AsyncSession, job_id: str, error: str) -> None:
    await session.execute(
        update(Job)
        .where(Job.job_id == job_id)
        .values(status="failed", error=error, claimed_at=None)
    )
    await session.commit()


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
