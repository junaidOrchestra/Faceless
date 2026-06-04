"""Video job persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Beat, BeatAssignment, VideoJob


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


async def claim_next_video_job(session: AsyncSession, timeout_s: float) -> VideoJob | None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=timeout_s)
    await session.execute(
        update(VideoJob)
        .where(
            VideoJob.status == "running",
            VideoJob.claimed_at.is_not(None),
            VideoJob.claimed_at < cutoff,
        )
        .values(status="queued", claimed_at=None)
    )
    await session.commit()

    result = await session.execute(
        select(VideoJob).where(VideoJob.status == "queued").order_by(VideoJob.created_at).limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        return None
    job.status = "running"
    job.claimed_at = now
    await session.commit()
    await session.refresh(job)
    return job


async def set_progress(session: AsyncSession, job_id: str, progress: str) -> None:
    await session.execute(
        update(VideoJob).where(VideoJob.id == job_id).values(progress=progress)
    )
    await session.commit()


async def mark_done(session: AsyncSession, job_id: str, result_url: str) -> None:
    await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id)
        .values(status="done", result_url=result_url, error=None, claimed_at=None)
    )
    await session.commit()


async def mark_failed(session: AsyncSession, job_id: str, error: str) -> None:
    await session.execute(
        update(VideoJob)
        .where(VideoJob.id == job_id)
        .values(status="failed", error=error, claimed_at=None)
    )
    await session.commit()


async def save_beats(session: AsyncSession, job_id: str, beats: list[dict[str, Any]]) -> None:
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
) -> None:
    session.add(
        BeatAssignment(
            video_job_id=job_id,
            beat_index=beat_index,
            platform=platform,
            media_url=media_url,
            kind=kind,
            score=score,
            attribution=attribution,
        )
    )
    await session.commit()


async def get_video_job(session: AsyncSession, job_id: str) -> VideoJob | None:
    return await session.get(VideoJob, job_id)
