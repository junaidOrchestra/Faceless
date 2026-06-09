"""Test helpers for minting Supabase-style access tokens (HS256)."""

from __future__ import annotations

import time
import uuid

import jwt

# Must match conftest's SUPABASE_JWT_SECRET / SUPABASE_JWT_AUDIENCE.
TEST_JWT_SECRET = "test-jwt-secret"
TEST_AUDIENCE = "authenticated"


def make_token(
    *,
    sub: str | None = None,
    email: str | None = None,
    secret: str = TEST_JWT_SECRET,
    audience: str = TEST_AUDIENCE,
    exp_offset_s: int = 3600,
) -> str:
    """Return a signed JWT mimicking a Supabase access token."""

    sub = sub or str(uuid.uuid4())
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": audience,
        "role": "authenticated",
        "iat": now,
        "exp": now + exp_offset_s,
    }
    if email is not None:
        claims["email"] = email
    return jwt.encode(claims, secret, algorithm="HS256")


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
