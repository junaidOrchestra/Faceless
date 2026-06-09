"""Supabase access-token (JWT) verification.

Supabase issues a signed JWT as the user's access token. Default projects sign
with **HS256** using the project JWT secret; projects migrated to asymmetric
keys sign with **RS256/ES256** and publish a JWKS document. The token's own
header tells us which one applies, so we choose per token:

* Header ``alg`` is HS256 → verify with ``SUPABASE_JWT_SECRET``.
* Header ``alg`` is asymmetric (RS256/ES256) → verify against the project's
  JWKS endpoint.

This matters because a project can have the legacy HS256 secret configured while
its user access tokens are actually signed asymmetrically. Picking the algorithm
from the header (instead of "secret set ⇒ HS256") handles that case.

Every path checks the signature, expiry (``exp``), and audience (``aud`` must be
``authenticated``). The token (and the secret) are never logged.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from ..config import Settings

logger = logging.getLogger(__name__)

# Algorithms we accept for the asymmetric (JWKS) path. HS256 is handled
# separately because it uses a shared secret, not a JWKS public key.
_ASYMMETRIC_ALGS = ["RS256", "ES256"]


class InvalidTokenError(Exception):
    """Raised when an access token is missing, malformed, expired, or untrusted."""


def _jwks_url(settings: Settings) -> str:
    """Resolve the JWKS endpoint (explicit override or derived from SUPABASE_URL)."""

    if settings.supabase_jwks_url:
        return settings.supabase_jwks_url
    if not settings.supabase_url:
        raise InvalidTokenError(
            "Asymmetric token verification requires SUPABASE_URL or SUPABASE_JWKS_URL."
        )
    base = settings.supabase_url.rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


@lru_cache(maxsize=4)
def _jwk_client(url: str) -> PyJWKClient:
    """Return a process-wide JWKS client (PyJWKClient caches fetched keys)."""

    return PyJWKClient(url, cache_keys=True)


def verify_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a Supabase access token and return its decoded claims.

    Args:
        token: The raw JWT from the ``Authorization: Bearer`` header.
        settings: Process settings carrying the Supabase verification config.

    Returns:
        The decoded JWT claims (including ``sub`` and ``email``).

    Raises:
        InvalidTokenError: If the token is missing/expired/wrong-audience or its
            signature cannot be verified, or if no verification method is
            configured.
    """

    if not token:
        raise InvalidTokenError("Missing access token.")

    options = {"require": ["exp", "sub"]}
    audience = settings.supabase_jwt_audience

    try:
        # The token header tells us how it was signed. Asymmetric tokens
        # (RS256/ES256) must be verified via JWKS even when an HS256 secret is
        # configured, because the secret only verifies HS256-signed tokens.
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("Access token is malformed.") from exc

        alg = header.get("alg", "")

        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise InvalidTokenError(
                    "Token is HS256-signed but SUPABASE_JWT_SECRET is not set."
                )
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=audience,
                options=options,
            )

        if alg in _ASYMMETRIC_ALGS:
            signing_key = _jwk_client(_jwks_url(settings)).get_signing_key_from_jwt(
                token
            )
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=_ASYMMETRIC_ALGS,
                audience=audience,
                options=options,
            )

        raise InvalidTokenError(f"Unsupported token algorithm: {alg!r}.")
    except InvalidTokenError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Access token has expired.") from exc
    except jwt.InvalidAudienceError as exc:
        raise InvalidTokenError(
            f"Access token has the wrong audience (expected {audience!r})."
        ) from exc
    except jwt.PyJWTError as exc:
        # Catch-all for signature/format errors. Do not include the token text.
        raise InvalidTokenError("Access token is invalid.") from exc
    except Exception as exc:  # noqa: BLE001 - e.g. JWKS fetch failure
        logger.warning("token verification failed: %s", type(exc).__name__)
        raise InvalidTokenError("Could not verify access token.") from exc
