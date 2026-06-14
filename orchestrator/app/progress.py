"""Granular per-job progress (stage + percent) in Redis, keyed by job_id.

Postgres remains the source of truth for terminal job *state* (status/result);
this is a fast, frequently-updated overlay the stateless web tier reads to show a
live progress bar. It is intentionally best-effort: every call swallows Redis
errors so a progress write can never break or wedge a pipeline stage.

Percent is the position within the job's *current phase* (0-100):

* Processing phase: ingesting -> transcribing -> llm -> awaiting_clip -> ready.
* Render phase (separate, user-triggered): render_queued -> rendering -> done.

Stages report an overall phase percent via :data:`PHASE_RANGE` so a caller only
needs to pass a stage name and an optional 0..1 fraction within that stage.
"""

from __future__ import annotations

import logging
import time

from .queue import get_redis

logger = logging.getLogger(__name__)

_TTL_S = 24 * 3600

# Each stage maps to an overall [start, end] percent within its phase, so the
# reported number climbs monotonically across the phase. The slow stages
# (transcribing, rendering) own the widest spans and report a real fraction.
PHASE_RANGE: dict[str, tuple[float, float]] = {
    # Processing phase.
    "ingesting": (0.0, 8.0),
    "transcribing": (8.0, 60.0),
    "transcribed": (60.0, 62.0),
    "llm": (62.0, 72.0),
    "awaiting_clip": (72.0, 96.0),
    "ready": (100.0, 100.0),
    # Render phase.
    "render_queued": (0.0, 3.0),
    "rendering": (3.0, 98.0),
    "done": (100.0, 100.0),
}


def _key(job_id: str) -> str:
    return f"progress:{job_id}"


def percent_for(stage: str, fraction: float = 0.0) -> float:
    """Overall phase percent for ``stage`` at ``fraction`` (0..1) through it."""

    start, end = PHASE_RANGE.get(stage, (0.0, 0.0))
    frac = max(0.0, min(1.0, fraction))
    return start + (end - start) * frac


def report_sync(job_id: str, stage: str, *, fraction: float = 0.0) -> None:
    """Thread-safe progress write for ffmpeg worker threads. Never raises."""

    pct = percent_for(stage, fraction)
    try:
        from redis import Redis

        from .config import get_settings

        redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        redis.hset(
            _key(job_id),
            mapping={
                "stage": stage,
                "percent": f"{pct:.1f}",
                "updated_at": f"{time.time():.0f}",
            },
        )
        redis.expire(_key(job_id), _TTL_S)
    except Exception:  # noqa: BLE001
        logger.debug("sync progress report failed for %s", job_id, exc_info=True)


async def report(job_id: str, stage: str, *, fraction: float = 0.0) -> None:
    """Write the job's current (stage, percent) overlay. Never raises."""

    pct = percent_for(stage, fraction)
    try:
        redis = get_redis()
        await redis.hset(
            _key(job_id),
            mapping={
                "stage": stage,
                "percent": f"{pct:.1f}",
                "updated_at": f"{time.time():.0f}",
            },
        )
        await redis.expire(_key(job_id), _TTL_S)
    except Exception:  # noqa: BLE001 - progress is best-effort
        logger.debug("progress report failed for %s", job_id, exc_info=True)


async def report_percent(job_id: str, stage: str, percent: float) -> None:
    """Write an explicit overall ``percent`` (0..100) with a stage label."""

    pct = max(0.0, min(100.0, float(percent)))
    try:
        redis = get_redis()
        await redis.hset(
            _key(job_id),
            mapping={
                "stage": stage,
                "percent": f"{pct:.1f}",
                "updated_at": f"{time.time():.0f}",
            },
        )
        await redis.expire(_key(job_id), _TTL_S)
    except Exception:  # noqa: BLE001
        logger.debug("progress report failed for %s", job_id, exc_info=True)


async def get(job_id: str) -> dict | None:
    """Return ``{"stage": str, "percent": float}`` or ``None`` if unset."""

    try:
        data = await get_redis().hgetall(_key(job_id))
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None
    try:
        return {"stage": data.get("stage"), "percent": float(data.get("percent") or 0.0)}
    except (TypeError, ValueError):
        return None


async def clear(job_id: str) -> None:
    """Drop the progress overlay (terminal state reached). Never raises."""

    try:
        await get_redis().delete(_key(job_id))
    except Exception:  # noqa: BLE001
        pass
