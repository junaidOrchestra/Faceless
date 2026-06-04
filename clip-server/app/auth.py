"""Bearer-token authentication dependency.

A single shared secret (``API_AUTH_SECRET``) protects every route except
``/health``. The token is compared in constant time to avoid leaking length/limit
information via timing. The secret is never logged.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

# ``auto_error=False`` lets us return a uniform 401 with a WWW-Authenticate header
# instead of FastAPI's default 403 when the header is missing.
_bearer_scheme = HTTPBearer(auto_error=False, description="Per-user bearer token.")


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency that rejects requests without a valid bearer token."""

    if credentials is None or not secrets.compare_digest(
        credentials.credentials, settings.api_auth_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
