"""Credit deduction is atomic, refunds are idempotent, and shortfalls block jobs."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.db import get_sessionmaker
from app.models import User
from app.services import credits as credit_service
from app.services import users as user_service

from ._auth import auth_header, make_token


async def _seed_user(user_id: str, credits: int) -> None:
    """Create a user with an exact balance (and a current-period grant stamp)."""

    sm = get_sessionmaker()
    async with sm() as session:
        await user_service.upsert_user(session, user_id, email=None)
        user = await session.get(User, user_id)
        assert user is not None
        user.credits = credits
        user.credits_granted_at = datetime.now(timezone.utc)
        await session.commit()


async def _balance(user_id: str) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        user = await session.get(User, user_id)
        return user.credits if user else -1


@pytest.mark.asyncio
async def test_concurrent_spend_never_oversells(client: AsyncClient) -> None:
    uid = f"spend-{uuid.uuid4()}"
    await _seed_user(uid, credits=4)
    sm = get_sessionmaker()

    async def attempt() -> bool:
        async with sm() as session:
            try:
                await credit_service.spend_credits(
                    session, uid, 2, reason="render", project_id=str(uuid.uuid4())
                )
                return True
            except credit_service.InsufficientCreditsError:
                return False

    results = await asyncio.gather(*[attempt() for _ in range(5)])
    # 4 credits, 2 per spend -> exactly 2 succeed, balance lands on 0.
    assert sum(results) == 2
    assert await _balance(uid) == 0


@pytest.mark.asyncio
async def test_refund_is_idempotent_per_project(client: AsyncClient) -> None:
    uid = f"refund-{uuid.uuid4()}"
    await _seed_user(uid, credits=0)
    pid = str(uuid.uuid4())
    sm = get_sessionmaker()

    async with sm() as session:
        first = await credit_service.refund_credits(session, uid, 3, project_id=pid)
    async with sm() as session:
        second = await credit_service.refund_credits(session, uid, 3, project_id=pid)

    assert first is True
    assert second is False  # duplicate refund is a no-op
    assert await _balance(uid) == 3


@pytest.mark.asyncio
async def test_insufficient_credits_blocks_render(client: AsyncClient, tmp_path) -> None:
    token = make_token(sub=f"broke-{uuid.uuid4()}", email="broke@example.com")
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"\x00" * 128)
    with audio.open("rb") as fh:
        create = await client.post(
            "/videos",
            files={"audio": ("narration.mp3", fh, "audio/mpeg")},
            headers=auth_header(token),
        )
    assert create.status_code == 202
    job_id = create.json()["video_job_id"]

    # Wait for the staged pipeline to reach `ready`.
    for _ in range(120):
        poll = await client.get(f"/videos/{job_id}", headers=auth_header(token))
        body = poll.json()
        if body["status"] == "ready":
            break
        if body["status"] == "failed":
            pytest.fail(body.get("error"))
        await asyncio.sleep(0.2)
    else:
        pytest.fail("job never reached ready")

    # Drain the user's balance, then a render must be rejected with 402.
    me = await client.get("/me", headers=auth_header(token))
    uid = me.json()["id"]
    await _seed_user(uid, credits=0)

    render = await client.post(f"/videos/{job_id}/render", headers=auth_header(token))
    assert render.status_code == 402
