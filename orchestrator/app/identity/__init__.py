"""Thin identity layer (Supabase Auth token verification).

This package is the ONLY place that knows the app authenticates users via
Supabase. It exposes:

* :func:`verify_access_token` — validate a Supabase JWT and return its claims.
* :class:`CurrentUser` — the minimal identity (id, email) extracted from a token.
* :func:`get_current_user` — a FastAPI dependency that verifies the bearer token,
  upserts the user into our own Postgres, ensures their monthly credit grant, and
  returns the :class:`CurrentUser`.

Project/credit logic depends only on ``CurrentUser.id`` (the Supabase ``sub``,
a UUID), so the identity provider can be swapped without touching it.
"""

from __future__ import annotations

from .dependencies import CurrentUser, CurrentUserDep, get_current_user
from .tokens import InvalidTokenError, verify_access_token

__all__ = [
    "CurrentUser",
    "CurrentUserDep",
    "get_current_user",
    "verify_access_token",
    "InvalidTokenError",
]
