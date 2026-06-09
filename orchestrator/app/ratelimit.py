"""Lightweight Redis-backed fixed-window rate limiting.

Reuses the process Redis client (already required for the job queues). A request
increments a per-key counter that expires after the window; exceeding the limit
returns HTTP 429. Fails open: if Redis is unreachable the request is allowed
(availability over strict limiting), and the limiter can be disabled entirely via
``RATE_LIMIT_ENABLED=false``.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from .config import Settings
from .queue import get_redis

logger = logging.getLogger(__name__)


async def enforce_rate_limit(
    settings: Settings,
    *,
    bucket: str,
    identity: str,
    limit: int,
    window_s: int = 60,
) -> None:
    """Allow or reject a request under a fixed-window counter.

    Args:
        settings: Process settings (honors ``rate_limit_enabled``).
        bucket: Logical action being limited, e.g. ``"create"``.
        identity: Caller identity (user id, falling back to client IP).
        limit: Max requests allowed per ``window_s``.
        window_s: Window length in seconds.

    Raises:
        HTTPException: ``429`` when the caller exceeds ``limit`` in the window.
    """

    if not settings.rate_limit_enabled or limit <= 0:
        return

    key = f"ratelimit:{bucket}:{identity}"
    try:
        redis = get_redis()
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window_s)
    except Exception:  # noqa: BLE001 - never block traffic on a limiter outage
        logger.warning("rate limiter unavailable; allowing request", exc_info=True)
        return

    if current > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for '{bucket}'. Try again shortly.",
            headers={"Retry-After": str(window_s)},
        )
