"""Smoke test: staged pipeline reaches `ready`, then renders to `done`."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from ._auth import auth_header, make_token

AUTH = auth_header(make_token(sub="smoke-user", email="smoke@example.com"))


async def _poll_until(client: AsyncClient, job_id: str, *targets: str) -> dict:
    for _ in range(120):
        poll = await client.get(f"/videos/{job_id}", headers=AUTH)
        assert poll.status_code == 200
        body = poll.json()
        if body["status"] in targets:
            return body
        if body["status"] == "failed":
            pytest.fail(body.get("error"))
        await asyncio.sleep(0.2)
    pytest.fail(f"video job stuck at {body['status']}")


@pytest.mark.asyncio
async def test_video_job_prepares_then_renders(client: AsyncClient, tmp_path) -> None:
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

    # Pipeline runs transcribe -> llm -> clip poll and stops at `ready`. Rendering
    # is on demand, so the job must NOT auto-advance to `done`.
    await _poll_until(client, job_id, "ready")

    # Request rendering explicitly.
    render = await client.post(f"/videos/{job_id}/render", headers=AUTH)
    assert render.status_code == 202
    assert render.json()["status"] == "render_queued"

    done = await _poll_until(client, job_id, "done")
    assert done.get("result_url")
