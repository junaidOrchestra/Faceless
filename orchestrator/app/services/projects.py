"""Project persistence, always scoped to an owner.

Every read is owner-scoped: :func:`get_project` returns ``None`` for a project
that exists but belongs to someone else, so the API can answer 404 (not 403) and
never leak existence. One project corresponds to one video.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project


async def create_project(
    session: AsyncSession,
    project_id: str,
    owner_id: str,
    *,
    title: str | None = None,
    input_type: str | None = None,
    status: str = "processing",
) -> Project:
    """Create a project owned by ``owner_id``."""

    project = Project(
        id=project_id,
        owner_id=owner_id,
        title=title,
        input_type=input_type,
        status=status,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def get_project(
    session: AsyncSession, project_id: str, owner_id: str
) -> Project | None:
    """Return the project only if it belongs to ``owner_id`` (else ``None``)."""

    result = await session.execute(
        select(Project).where(
            Project.id == project_id, Project.owner_id == owner_id
        )
    )
    return result.scalar_one_or_none()


async def list_projects(session: AsyncSession, owner_id: str) -> list[Project]:
    """Return all of the owner's projects, newest first."""

    result = await session.execute(
        select(Project)
        .where(Project.owner_id == owner_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars())


async def count_projects(session: AsyncSession, owner_id: str) -> int:
    """Return how many projects ``owner_id`` currently owns (for quota checks)."""

    result = await session.execute(
        select(func.count()).select_from(Project).where(Project.owner_id == owner_id)
    )
    return int(result.scalar_one())


async def delete_project(
    session: AsyncSession, project_id: str, owner_id: str
) -> bool:
    """Delete the owner's project row. Returns ``True`` if a row was removed.

    Owner-scoped so a caller can never delete another user's project. The
    associated job/beats and stored media are cleaned up by the caller.
    """

    result = await session.execute(
        delete(Project).where(
            Project.id == project_id, Project.owner_id == owner_id
        )
    )
    await session.commit()
    return bool(result.rowcount)


async def update_project(
    session: AsyncSession,
    project_id: str,
    *,
    status: str | None = None,
    result_url: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Patch mutable project fields (status / result_url)."""

    values: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if status is not None:
        values["status"] = status
    if result_url is not None:
        values["result_url"] = result_url
    if extra:
        values.update(extra)
    await session.execute(
        update(Project).where(Project.id == project_id).values(**values)
    )
    await session.commit()
