"""Shared-Redis result publishing.

The clip-server stays Postgres-backed for job *state* and processing, but once a
job reaches a terminal state it publishes the result onto a shared cloud Redis
queue. The orchestrator consumes from that queue (reliable two-list pattern:
``<name>:queue`` pending, ``<name>:processing`` claimed) instead of HTTP-polling
``GET /jobs/{id}``.

The published envelope mirrors the orchestrator's ``ClipJobStatusResponse``::

    {"job_id": "<id>", "status": "done"|"failed", "items": [...], "error": null}
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from redis.asyncio import Redis

from .config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_redis() -> Redis:
    """Process-wide async Redis client (decoded to ``str``)."""

    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def publish_clip_result(
    job_id: str,
    status: str,
    *,
    items: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    """Right-push a finished job's result onto the shared Redis queue.

    Best-effort: a Redis failure is logged but never propagates — the job is
    already durable in Postgres, and the orchestrator's age backstop fails any
    job whose result never arrives, so a transient publish error degrades
    gracefully rather than crashing the worker.
    """

    settings = get_settings()
    if not settings.publish_results:
        return

    envelope: dict[str, Any] = {"job_id": job_id, "status": status}
    if items is not None:
        envelope["items"] = items
    if error is not None:
        envelope["error"] = error

    key = f"{settings.clip_result_queue}:queue"
    try:
        await get_redis().rpush(key, json.dumps(envelope))
        logger.info("published clip result for %s (status=%s) to %s", job_id, status, key)
    except Exception:  # noqa: BLE001 - publishing must not crash the worker
        logger.exception("failed to publish clip result for %s to redis", job_id)
