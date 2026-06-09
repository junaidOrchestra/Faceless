"""get_current_user accepts valid tokens and rejects bad ones."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from ._auth import auth_header, make_token


@pytest.mark.asyncio
async def test_valid_token_accepted_and_user_upserted(client: AsyncClient) -> None:
    token = make_token(sub="user-valid", email="valid@example.com")
    res = await client.get("/me", headers=auth_header(token))
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "user-valid"
    assert body["email"] == "valid@example.com"
    assert body["tier"] == "free"
    assert body["credits"] == body["tier_info"]["monthly_credits"]
    assert body["credits"] > 0


@pytest.mark.asyncio
async def test_missing_token_rejected(client: AsyncClient) -> None:
    res = await client.get("/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_invalid_signature_rejected(client: AsyncClient) -> None:
    token = make_token(sub="user-x", secret="wrong-secret")
    res = await client.get("/me", headers=auth_header(token))
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(client: AsyncClient) -> None:
    token = make_token(sub="user-x", exp_offset_s=-10)
    res = await client.get("/me", headers=auth_header(token))
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience_rejected(client: AsyncClient) -> None:
    token = make_token(sub="user-x", audience="not-authenticated")
    res = await client.get("/me", headers=auth_header(token))
    assert res.status_code == 401
