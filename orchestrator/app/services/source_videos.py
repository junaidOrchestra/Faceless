"""Persistence for uploaded source media (direct-to-B2)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..media_validation import MediaProbe
from ..models import SourceVideo


async def create_uploaded(
    session: AsyncSession,
    *,
    source_id: str,
    owner_id: str,
    r2_key: str,
    filename: str | None,
    content_type: str | None,
    size_bytes: int | None,
    video_job_id: str | None = None,
    status: str = "uploaded",
) -> SourceVideo:
    row = SourceVideo(
        id=source_id,
        owner_id=owner_id,
        video_job_id=video_job_id,
        r2_key=r2_key,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        status=status,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_owned(
    session: AsyncSession, source_id: str, owner_id: str
) -> SourceVideo | None:
    result = await session.execute(
        select(SourceVideo).where(SourceVideo.id == source_id, SourceVideo.owner_id == owner_id)
    )
    return result.scalar_one_or_none()


async def get_by_job_id(session: AsyncSession, job_id: str) -> SourceVideo | None:
    result = await session.execute(
        select(SourceVideo).where(SourceVideo.video_job_id == job_id)
    )
    return result.scalar_one_or_none()


async def apply_probe(
    session: AsyncSession,
    source_id: str,
    probe: MediaProbe,
    *,
    size_bytes: int | None = None,
) -> None:
    values: dict = {
        "status": "ready",
        "duration_s": probe.duration_s,
        "width": probe.width,
        "height": probe.height,
        "fps": probe.fps,
        "video_codec": probe.video_codec,
        "audio_codec": probe.audio_codec,
        "updated_at": datetime.now(timezone.utc),
    }
    if size_bytes is not None:
        values["size_bytes"] = size_bytes
    await session.execute(
        update(SourceVideo).where(SourceVideo.id == source_id).values(**values)
    )
    await session.commit()


async def get(session: AsyncSession, source_id: str) -> SourceVideo | None:
    return await session.get(SourceVideo, source_id)


async def set_proxy_ready(
    session: AsyncSession,
    source_id: str,
    *,
    proxy_key: str,
    hls_playlist_key: str | None = None,
) -> None:
    values: dict = {
        "proxy_key": proxy_key,
        "status": "proxy_ready",
        "updated_at": datetime.now(timezone.utc),
    }
    if hls_playlist_key is not None:
        values["hls_playlist_key"] = hls_playlist_key
    await session.execute(
        update(SourceVideo).where(SourceVideo.id == source_id).values(**values)
    )
    await session.commit()


async def set_thumbnails_ready(
    session: AsyncSession,
    source_id: str,
    *,
    index_key: str,
    index: dict,
) -> None:
    await session.execute(
        update(SourceVideo)
        .where(SourceVideo.id == source_id)
        .values(
            thumbs_index_key=index_key,
            thumbs_index=index,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def list_pending_thumbnail_ids(session: AsyncSession) -> list[str]:
    """Video sources with a proxy but no thumbnail sprites yet (queue rebuild)."""

    result = await session.execute(
        select(SourceVideo.id)
        .where(
            SourceVideo.thumbs_index.is_(None),
            SourceVideo.proxy_key.isnot(None),
            SourceVideo.content_type.like("video/%"),
        )
        .order_by(SourceVideo.created_at)
    )
    return [row[0] for row in result.all()]


async def list_pending_proxy_ids(session: AsyncSession) -> list[str]:
    """Video sources that finished probing but have no proxy yet (queue rebuild)."""

    result = await session.execute(
        select(SourceVideo.id)
        .where(
            SourceVideo.proxy_key.is_(None),
            SourceVideo.status == "ready",
            SourceVideo.content_type.like("video/%"),
        )
        .order_by(SourceVideo.created_at)
    )
    return [row[0] for row in result.all()]


async def mark_proxy_failed(session: AsyncSession, source_id: str, error: str) -> None:
    """Record a proxy-build failure WITHOUT failing the source.

    The proxy is an optimization; if it can't be built the editor falls back to
    streaming the full-quality original, so the source stays usable.
    """

    await session.execute(
        update(SourceVideo)
        .where(SourceVideo.id == source_id)
        .values(error=error[:2000], updated_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def mark_failed(session: AsyncSession, source_id: str, error: str) -> None:
    await session.execute(
        update(SourceVideo)
        .where(SourceVideo.id == source_id)
        .values(
            status="failed",
            error=error[:2000],
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
