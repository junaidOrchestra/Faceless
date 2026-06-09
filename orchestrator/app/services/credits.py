"""Credit ledger operations: atomic spend, idempotent refund, and reads.

``users.credits`` is the running balance; ``credit_transactions`` is the
append-only ledger. Spending takes a row lock so two concurrent renders can
never double-spend the same balance. Refunds are idempotent per project (guarded
by a partial unique index) so a retried failure path refunds at most once.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CreditTransaction, User


class InsufficientCreditsError(Exception):
    """Raised when a user's balance cannot cover a spend."""

    def __init__(self, *, required: int, available: int) -> None:
        self.required = required
        self.available = available
        super().__init__(
            f"Insufficient credits: need {required}, have {available}."
        )


async def spend_credits(
    session: AsyncSession,
    user_id: str,
    amount: int,
    *,
    reason: str,
    project_id: str | None = None,
) -> int:
    """Atomically deduct ``amount`` credits and write a ``-spend`` ledger row.

    The user row is locked with ``SELECT ... FOR UPDATE`` for the duration of the
    transaction, so a concurrent spend blocks until this one commits — preventing
    a double-spend. Raises :class:`InsufficientCreditsError` (after releasing the
    lock) if the balance is too low. Returns the new balance.
    """

    if amount <= 0:
        # Nothing to charge (e.g. an empty render); record nothing.
        user = await session.get(User, user_id)
        return user.credits if user else 0

    locked = (
        await session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None:
        raise InsufficientCreditsError(required=amount, available=0)
    if locked.credits < amount:
        available = locked.credits
        await session.rollback()
        raise InsufficientCreditsError(required=amount, available=available)

    locked.credits -= amount
    session.add(
        CreditTransaction(
            user_id=user_id,
            delta=-amount,
            reason=reason,
            project_id=project_id,
        )
    )
    await session.commit()
    return locked.credits


async def refund_credits(
    session: AsyncSession,
    user_id: str,
    amount: int,
    *,
    project_id: str,
    reason: str = "refund",
) -> bool:
    """Refund ``amount`` credits for a failed project (idempotent per project).

    Returns ``True`` if a refund was actually applied, ``False`` if one already
    existed for the project (the partial unique index turns a duplicate into a
    no-op). Locks the user row before crediting so the balance update is safe
    against a concurrent spend/grant.
    """

    if amount <= 0:
        return False

    stmt = (
        insert(CreditTransaction)
        .values(user_id=user_id, delta=amount, reason=reason, project_id=project_id)
        .on_conflict_do_nothing(
            index_elements=[CreditTransaction.project_id],
            index_where=text("reason = 'refund' AND project_id IS NOT NULL"),
        )
    )
    result = await session.execute(stmt)
    if not result.rowcount:
        await session.rollback()
        return False

    locked = (
        await session.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if locked is not None:
        locked.credits += amount
    await session.commit()
    return True


async def list_transactions(
    session: AsyncSession, user_id: str, *, limit: int = 100
) -> list[CreditTransaction]:
    """Return a user's ledger entries, newest first."""

    result = await session.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
        .limit(limit)
    )
    return list(result.scalars())
