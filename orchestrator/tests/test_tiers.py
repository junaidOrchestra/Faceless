"""Tier limits: an over-limit render is rejected before processing."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app import tiers
from app.services import video_jobs as job_service

from ._auth import auth_header, make_token


def test_check_video_length_unit() -> None:
    # Public tiers cap at 1 hour; longer videos violate it, shorter ones do not.
    assert tiers.check_video_length("free", 3601) is not None
    assert tiers.check_video_length("free", 30) is None
    # Higher tiers share the same one-hour cap.
    assert tiers.check_video_length("professional", 3600) is None
    # Admin has no length limit (max_video_seconds == 0).
    assert tiers.check_video_length("admin", 99999) is None


def test_admin_tier_internal_only() -> None:
    cfg = tiers.get_tier_config("admin")
    assert cfg.unlimited_credits is True
    assert cfg.watermark is True
    assert cfg.max_video_seconds == 0
    # Hidden from every public listing.
    assert "admin" not in tiers.PUBLIC_TIERS
    assert "admin" not in tiers.TIERS


def test_credit_cost_rounds_up() -> None:
    assert tiers.credit_cost_for_seconds(0) == 0
    assert tiers.credit_cost_for_seconds(1) == 1
    assert tiers.credit_cost_for_seconds(15) == 1
    assert tiers.credit_cost_for_seconds(16) == 2


def test_check_project_quota_unit() -> None:
    # Free tier caps at 5 projects: the 5th create (count==4) is fine, the 6th
    # (count==5) is rejected.
    assert tiers.check_project_quota("free", 4) is None
    assert tiers.check_project_quota("free", 5) is not None
    # Professional is unlimited (max_projects == 0): any count is allowed.
    assert tiers.check_project_quota("professional", 9999) is None


def test_check_concurrency_unit() -> None:
    # Free tier allows 1 in-flight job: a second concurrent create is rejected.
    assert tiers.check_concurrency("free", 0) is None
    assert tiers.check_concurrency("free", 1) is not None
    # Individual allows 3 concurrent jobs.
    assert tiers.check_concurrency("individual", 2) is None
    assert tiers.check_concurrency("individual", 3) is not None
    # Professional concurrency cap is non-zero but generous.
    assert tiers.check_concurrency("professional", 9) is None


@pytest.mark.asyncio
async def test_over_limit_render_rejected(client: AsyncClient, tmp_path, monkeypatch) -> None:
    token = make_token(sub=f"longvid-{uuid.uuid4()}", email="long@example.com")
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

    # Force the measured duration well past the free tier's 1-hour cap.
    async def _fake_duration(_session, _job_id: str) -> float:
        return 9999.0

    monkeypatch.setattr(job_service, "get_job_duration_seconds", _fake_duration)

    render = await client.post(f"/videos/{job_id}/render", headers=auth_header(token))
    assert render.status_code == 400
    assert "tier" in render.json()["detail"].lower()
