"""Feedback persistence — append-only user suggestions/bug reports."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Feedback


async def create_feedback(
    session: AsyncSession,
    *,
    user_id: str,
    category: str,
    message: str,
    rating: int | None = None,
    email: str | None = None,
    page: str | None = None,
    user_agent: str | None = None,
) -> Feedback:
    """Store one feedback submission and return the persisted row."""

    row = Feedback(
        user_id=user_id,
        category=category,
        message=message.strip(),
        rating=rating,
        email=(email or None),
        page=page,
        user_agent=user_agent,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row
