"""FastAPI auth dependency: verify the Supabase token and resolve the user.

``get_current_user`` is the single entry point every protected route depends on.
It verifies the bearer access token, extracts the Supabase ``sub`` as the user
id, upserts the user mirror from the token claims on first sight, applies any due
monthly credit grant, and returns a minimal :class:`CurrentUser`.

Downstream code only ever uses ``CurrentUser.id`` (and occasionally ``email``),
so the rest of the app has no dependency on Supabase specifically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import Settings, get_settings
from ..db import get_session
from ..services import users as user_service
from .tokens import InvalidTokenError, verify_access_token

_bearer = HTTPBearer(auto_error=False)


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

    # Mirror the identity into our own Postgres and apply any due grant. These
    # run per-request but are cheap: the upsert is a single statement and the
    # grant short-circuits once granted for the current period.
    await user_service.upsert_user(session, sub, email=email)
    await user_service.ensure_monthly_grant(session, sub)

    return CurrentUser(id=sub, email=email)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
