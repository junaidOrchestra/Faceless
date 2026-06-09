"""User A cannot read user B's project or its result (404, never 403)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ._auth import auth_header, make_token


async def _create_job(client: AsyncClient, token: str, tmp_path) -> str:
    audio = tmp_path / "narration.mp3"
    audio.write_bytes(b"\x00" * 128)
    with audio.open("rb") as fh:
        res = await client.post(
            "/videos",
            files={"audio": ("narration.mp3", fh, "audio/mpeg")},
            headers=auth_header(token),
        )
    assert res.status_code == 202
    return res.json()["video_job_id"]


@pytest.mark.asyncio
async def test_user_b_cannot_read_user_a_job(client: AsyncClient, tmp_path) -> None:
    token_a = make_token(sub="owner-a", email="a@example.com")
    token_b = make_token(sub="intruder-b", email="b@example.com")

    job_id = await _create_job(client, token_a, tmp_path)

    # Owner can read it.
    own = await client.get(f"/videos/{job_id}", headers=auth_header(token_a))
    assert own.status_code == 200

    # Stranger gets 404 (not 403) for the job, its beats, project, and download.
    for path in (
        f"/videos/{job_id}",
        f"/videos/{job_id}/beats",
        f"/videos/{job_id}/download",
        f"/projects/{job_id}",
    ):
        res = await client.get(path, headers=auth_header(token_b))
        assert res.status_code == 404, f"{path} leaked to non-owner: {res.status_code}"


@pytest.mark.asyncio
async def test_projects_list_is_owner_scoped(client: AsyncClient, tmp_path) -> None:
    token_a = make_token(sub="list-a")
    token_b = make_token(sub="list-b")
    job_id = await _create_job(client, token_a, tmp_path)

    a_list = await client.get("/projects", headers=auth_header(token_a))
    assert a_list.status_code == 200
    assert any(p["id"] == job_id for p in a_list.json()["projects"])

    b_list = await client.get("/projects", headers=auth_header(token_b))
    assert b_list.status_code == 200
    assert all(p["id"] != job_id for p in b_list.json()["projects"])
