"""Redis-backed dispatch queues for the staged video pipeline.

Postgres stays the source of truth for job *state* (status/progress/result).
Redis fans pending ``video_job`` ids out to the per-stage worker pools so each
stage (transcribe -> llm -> render) scales independently and no two workers
claim the same job.

Each stage has its own :class:`RedisQueue` using the classic reliable two-list
pattern:

* ``<name>:queue``      — FIFO list of job ids waiting for this stage.
* ``<name>:processing`` — job ids a worker has taken but not finished yet.

A worker atomically moves an id from ``queue`` to ``processing`` (``BLMOVE``),
processes it, then removes it from ``processing`` (``ack``). If the process dies
mid-job the id is left in ``processing``; on startup the queues are rebuilt from
Postgres (per stage) so nothing is lost even if Redis was flushed.

The clip-search stage has no *dispatch* queue (the LLM stage submits directly to
the clip-server). Instead a single cross-service *result* queue
(``clip_result``) carries finished clip-search results back: the clip-server
right-pushes a JSON envelope when a job finishes and an orchestrator worker
consumes it, transforms it into durable editor state, and marks the job ready.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from redis.asyncio import Redis

from .config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_redis() -> Redis:
    """Process-wide async Redis client (decoded to ``str``)."""

    return Redis.from_url(get_settings().redis_url, decode_responses=True)


class RedisQueue:
    """One reliable FIFO work queue for a pipeline stage."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.queue_key = f"{name}:queue"
        self.processing_key = f"{name}:processing"

    async def enqueue(self, job_id: str) -> None:
        """Append a job id to the pending queue (FIFO via right-push)."""

        await get_redis().rpush(self.queue_key, job_id)

    async def claim(self, timeout_s: float) -> str | None:
        """Block up to ``timeout_s`` for the next job id, moving it to processing.

        Returns ``None`` on timeout so the worker can re-check its stop flag.
        """

        return await get_redis().blmove(
            self.queue_key, self.processing_key, timeout_s, src="LEFT", dest="RIGHT"
        )

    async def ack(self, job_id: str) -> None:
        """Remove a finished job id from the processing backup list."""

        await get_redis().lrem(self.processing_key, 0, job_id)

    async def requeue_processing(self) -> int:
        """Move any orphaned entries from ``processing`` back to the pending queue.

        Used for queues whose pending set can't be rebuilt from Postgres (e.g. the
        cross-service clip-result queue, whose messages originate in the
        clip-server). On startup we re-deliver anything a previous process claimed
        but didn't ack so no finished clip result is lost.
        """

        redis = get_redis()
        moved = 0
        while await redis.lmove(self.processing_key, self.queue_key, src="RIGHT", dest="LEFT"):
            moved += 1
        if moved:
            logger.info("requeued %s orphaned entries on %s", moved, self.name)
        return moved

    async def rebuild(self, job_ids: list[str]) -> None:
        """Reset this queue to exactly ``job_ids`` (oldest first).

        Called on startup after the DB statuses for this stage are reconciled so
        the in-memory queue matches the database and any ids orphaned in
        ``processing`` by a previous process are discarded (they're back in
        ``job_ids``).
        """

        redis = get_redis()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.delete(self.queue_key)
            pipe.delete(self.processing_key)
            if job_ids:
                pipe.rpush(self.queue_key, *job_ids)
            await pipe.execute()
        logger.info("rebuilt redis queue %s from db (%s pending)", self.name, len(job_ids))


# Stage queues. clip-search is intentionally absent (poller scans the DB).
transcribe_queue = RedisQueue("transcribe")
llm_queue = RedisQueue("llm")
render_queue = RedisQueue("render")

# Cross-service queue: the clip-server right-pushes finished clip-search results
# (JSON envelopes) here; an orchestrator worker consumes and applies them. Named
# from settings so both services agree on the Redis key.
clip_result_queue = RedisQueue(get_settings().clip_result_queue)
