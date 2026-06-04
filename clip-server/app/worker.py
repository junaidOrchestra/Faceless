"""In-process background worker for durable Postgres-backed jobs."""

from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .db import get_sessionmaker
from .embedding.base import Embedder
from .pipeline import run_job
from .services import jobs as job_service

logger = logging.getLogger(__name__)


class JobWorker:
    """Polls Postgres for ``queued`` jobs and runs the CLIP ranking pipeline."""

    def __init__(self, settings: Settings, embedder: Embedder) -> None:
        self._settings = settings
        self._embedder = embedder
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="clip-job-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _loop(self) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                async with sessionmaker() as session:
                    pruned = await job_service.prune_expired_jobs(
                        session, self._settings.job_ttl_s
                    )
                    if pruned:
                        logger.info("pruned %s expired jobs", pruned)

                async with sessionmaker() as session:
                    job = await job_service.claim_next_job(
                        session, self._settings.job_running_timeout_s
                    )
                    if job is None:
                        await asyncio.sleep(self._settings.worker_poll_interval_s)
                        continue

                    payload = job.items_input
                    items = payload.get("items") or []
                    credentials = payload.get("credentials") or {}
                    options = payload.get("options") or {}
                    try:
                        results = await run_job(
                            session,
                            self._embedder,
                            self._settings,
                            items,
                            credentials,
                            options,
                        )
                        await job_service.mark_job_done(session, job.job_id, results)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("job %s failed", job.job_id)
                        await job_service.mark_job_failed(session, job.job_id, str(exc))
            except Exception:  # noqa: BLE001
                logger.exception("worker loop error")
                await asyncio.sleep(self._settings.worker_poll_interval_s)
