"""Smoke test: submit job with stub source, poll until done, assert assets cached."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Asset

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.mark.asyncio
async def test_jobs_submit_poll_and_assets(client: AsyncClient) -> None:
    job_id = f"smoke-{uuid.uuid4()}"
    create = await client.post(
        "/jobs",
        json={
            "job_id": job_id,
            "items": [{"ref": "beat-0", "keyword": "test keyword", "sources": ["stub"]}],
            "options": {"min_score": 0.0, "per_page": 3},
        },
        headers=AUTH,
    )
    assert create.status_code == 202
    assert create.json()["job_id"] == job_id

    status = "queued"
    items: list = []
    for _ in range(60):
        poll = await client.get(f"/jobs/{job_id}", headers=AUTH)
        assert poll.status_code == 200
        body = poll.json()
        status = body["status"]
        if status == "done":
            items = body["items"]
            break
        if status == "failed":
            pytest.fail(body.get("error") or "job failed")
        await asyncio.sleep(0.25)
    else:
        pytest.fail(f"job did not finish, last status={status}")

    assert items and items[0]["ref"] == "beat-0"
    assert items[0]["assets"], "expected ranked assets from stub source"

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(Asset).where(Asset.platform == "stub"))
        cached = result.scalars().all()
    assert cached, "assets table should contain stub embeddings"
