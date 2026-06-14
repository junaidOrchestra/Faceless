"""Redis-dispatch implementation of :class:`ClipClient`.

Instead of the legacy ``POST /jobs`` HTTP call, this right-pushes a job envelope
onto a shared Redis dispatch queue that the clip-server consumes. This removes
HTTP ingress from the submit path entirely, so hosted-platform rate limits (e.g.
a 429 on the clip-server's public URL) can never fail a render at submit time.

The envelope mirrors the clip-server's ``CreateJobRequest`` body so the consumer
can treat it exactly like an HTTP submit::

    {"job_id": "<id>", "items": [...], "credentials": {}, "options": {...}}

Source API keys are intentionally NOT sent (same as the HTTP client): the
clip-server fills them from its own environment. Idempotency is handled by the
clip-server's upsert-on-``job_id``, so a duplicate dispatch (e.g. a stage rerun
after a restart) is harmless.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..queue import clip_dispatch_queue
from .base import ClipClient
from .schemas import ClipJobStatusResponse

logger = logging.getLogger(__name__)


class RedisClipClient(ClipClient):
    async def submit(
        self,
        job_id: str,
        items: list[dict[str, Any]],
        credentials: dict[str, str | None],
        sources: list[str] | None,
        *,
        orientation: str | None = None,
        quality: str | None = None,
        rank: bool = True,
        per_page: int | None = None,
    ) -> None:
        # Keys come from the clip-server's environment; never put them on the wire.
        del credentials
        options: dict[str, Any] = {"min_score": 0.15, "rank": rank}
        if orientation is not None:
            options["orientation"] = orientation
        if quality is not None:
            options["quality"] = quality
        if per_page is not None:
            options["per_page"] = per_page
        envelope = {
            "job_id": job_id,
            "items": [
                {
                    "ref": str(it["ref"]),
                    "keyword": str(it["keyword"]),
                    "sources": it.get("sources") or sources,
                }
                for it in items
            ],
            "credentials": {},
            "options": options,
        }
        await clip_dispatch_queue.enqueue(json.dumps(envelope))
        logger.info(
            "dispatched clip job %s (%s items) to redis %s",
            job_id,
            len(envelope["items"]),
            clip_dispatch_queue.queue_key,
        )

    async def poll(self, job_id: str) -> ClipJobStatusResponse:
        # Results arrive via the shared clip-result Redis queue (consumed by the
        # clip-result consumer), so this transport is never polled. If something
        # does poll it, that's a wiring bug worth surfacing loudly.
        raise NotImplementedError(
            "RedisClipClient does not poll; results arrive via the clip-result queue."
        )
