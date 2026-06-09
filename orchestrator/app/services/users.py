"""User mirror persistence + monthly credit grants.

The user row is our own copy of the Supabase identity plus app-owned state
(tier, credit balance). On the first authenticated request the user is upserted
from the token claims; on every request a cheap check-on-use grant tops the
account up at the start of a new monthly period (no scheduler required, though a
scheduled job could call :func:`ensure_monthly_grant` too).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CreditTransaction, User
from ..tiers import get_tier_config


async def upsert_user(
    session: AsyncSession,
    user_id: str,
    *,
    email: str | None,
    name: str | None = None,
) -> User:
    """Insert the user (first sight) or refresh mutable identity fields.

    Keyed by the Supabase ``sub``. App-owned columns (tier, credits) are never
    overwritten here — only the identity mirror (email/name). A brand-new user is
    created with zero credits; :func:`ensure_monthly_grant` then applies the
    initial free grant in the same request.
    """

    stmt = (
        insert(User)
        .values(id=user_id, email=email, name=name, tier="free", credits=0)
        .on_conflict_do_update(
            index_elements=[User.id],
            set_={"email": email, "name": name},
        )
        .returning(User)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()


def _same_period(a: datetime | None, b: datetime) -> bool:
    """True when two timestamps fall in the same calendar (UTC) month."""

    if a is None:
        return False
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    return (a.year, a.month) == (b.year, b.month)


async def ensure_monthly_grant(session: AsyncSession, user_id: str) -> User:
    """Grant the tier's monthly credits if a new period has started.

    Cheap fast-path: if the user was already granted this period, returns
    immediately. Otherwise it locks the row (``SELECT ... FOR UPDATE``), sets the
    balance to the tier's monthly grant, stamps ``credits_granted_at``, and writes
    a ``+grant`` ledger row — all in one transaction so concurrent requests can't
    double-grant.

    NOTE: this resets the balance to the monthly grant at each period boundary.
    Purchased credit packs (a later feature) should be added on top *within* a
    period; the period reset is where a packs-aware policy would hook in.
    """

    now = datetime.now(timezone.utc)

    # Fast path: avoid taking a row lock on the common already-granted case.
    user = await session.get(User, user_id)
    if user is not None and _same_period(user.credits_granted_at, now):
        return user

    locked = (
        await session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None:
        # User vanished between upsert and grant; nothing to do.
        await session.rollback()
        return user  # type: ignore[return-value]

    if _same_period(locked.credits_granted_at, now):
        # Another concurrent request granted while we waited for the lock.
        await session.commit()
        return locked

    grant = get_tier_config(locked.tier).monthly_credits
    locked.credits = grant
    locked.credits_granted_at = now
    session.add(
        CreditTransaction(
            user_id=user_id,
            delta=grant,
            reason="grant",
            project_id=None,
        )
    )
    await session.commit()
    await session.refresh(locked)
    return locked


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    """Return the user row, or ``None`` if it does not exist."""

    return await session.get(User, user_id)
