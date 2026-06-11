"""FastAPI auth dependency: verify the Supabase token and resolve the user.

``get_current_user`` is the single entry point every protected route depends on.
It verifies the bearer access token, extracts the Supabase ``sub`` as the user
id, upserts the user mirror from the token claims on first sight, applies any due
monthly credit grant, and returns a minimal :class:`CurrentUser`.

Downstream code only ever uses ``CurrentUser.id`` (and occasionally ``email``),
so the rest of the app has no dependency on Supabase specifically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import Settings, get_settings
from ..db import get_session
from ..services import users as user_service
from .tokens import InvalidTokenError, verify_access_token

_bearer = HTTPBearer(auto_error=False)

# Per-request identity bookkeeping (upsert mirror + monthly grant) is correct but
# costs a few DB round-trips to the (cloud) database on EVERY authenticated call —
# noticeable on hot, read-only endpoints like GET /me polled from the header. We
# only actually need it occasionally (first sight, email change, a new monthly
# period), so throttle it with a small in-process TTL cache: a user seen within
# the window skips the upsert/grant entirely. Credit balances stay accurate
# because every endpoint still reads the live row; only the (idempotent)
# write-path is debounced. Per-process and best-effort — a cold worker simply
# runs it once.
_SEEN_TTL_S = 600.0
_SEEN_MAX = 10_000
_seen_users: dict[str, float] = {}


def _recently_synced(user_id: str) -> bool:
    """True if we ran the upsert/grant for this user within the TTL window."""

    now = time.monotonic()
    last = _seen_users.get(user_id)
    if last is not None and now - last < _SEEN_TTL_S:
        return True
    # Bound memory: drop the whole map if it grows unexpectedly large (cheap and
    # rare). The next request for each user just re-syncs once.
    if len(_seen_users) >= _SEEN_MAX:
        _seen_users.clear()
    _seen_users[user_id] = now
    return False


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The authenticated caller, resolved from a verified access token."""

    id: str
    email: str | None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    session=Depends(get_session),
) -> CurrentUser:
    """Authenticate the request and return the current user.

    Raises ``401`` if the bearer token is missing, invalid, expired, or carries
    the wrong audience. Tokens and secrets are never logged.
    """

    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing or invalid bearer token.")

    try:
        claims = verify_access_token(credentials.credentials, settings)
    except InvalidTokenError as exc:
        raise _unauthorized(str(exc)) from exc

    sub = claims.get("sub")
    if not sub:
        raise _unauthorized("Token is missing the subject claim.")
    email = claims.get("email")

    # Mirror the identity into our own Postgres and apply any due grant. Both are
    # idempotent, so we debounce them per user (TTL cache) to avoid spending DB
    # round-trips on every authenticated request (e.g. the header polling /me).
    if not _recently_synced(sub):
        await user_service.upsert_user(session, sub, email=email)
        await user_service.ensure_monthly_grant(session, sub)

    return CurrentUser(id=sub, email=email)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
