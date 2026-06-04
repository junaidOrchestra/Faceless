"""Smoke test: stub pipeline reaches video job status done."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

AUTH = {"Authorization": "Bearer test-secret"}


@pytest.mark.asyncio
async def test_video_job_reaches_done(client: AsyncClient, tmp_path) -> None:
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"\x00" * 128)

    with audio.open("rb") as fh:
        create = await client.post(
            "/videos",
            files={"audio": ("narration.mp3", fh, "audio/mpeg")},
            headers=AUTH,
        )
    assert create.status_code == 202
    job_id = create.json()["video_job_id"]

    status = "queued"
    for _ in range(80):
        poll = await client.get(f"/videos/{job_id}", headers=AUTH)
        assert poll.status_code == 200
        body = poll.json()
        status = body["status"]
        if status == "done":
            assert body.get("result_url")
            return
        if status == "failed":
            pytest.fail(body.get("error"))
        await asyncio.sleep(0.2)
    pytest.fail(f"video job stuck at {status}")
