"""In-process background worker for durable Postgres-backed jobs."""

from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .db import get_sessionmaker
from .embedding.base import Embedder
from .pipeline import run_job
from .queue import publish_clip_result
from .services import jobs as job_service

logger = logging.getLogger(__name__)


class JobWorker:
    """Polls Postgres for ``queued`` jobs and runs the CLIP ranking pipeline."""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        *,
        embed_lock: asyncio.Lock | None = None,
    ) -> None:
        self._settings = settings
        self._embedder = embedder
        self._embed_lock = embed_lock or asyncio.Lock()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if not self._tasks:
            self._tasks = [
                asyncio.create_task(self._loop(), name="clip-job-worker"),
                asyncio.create_task(self._stale_job_sweeper(), name="clip-stale-job-sweeper"),
            ]

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks = []

    async def _heartbeat_job(self, job_id: str) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            await asyncio.sleep(self._settings.job_heartbeat_interval_s)
            try:
                async with sessionmaker() as session:
                    refreshed = await job_service.heartbeat_job(session, job_id)
                if not refreshed:
                    return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - heartbeat failure should not kill the job
                logger.warning("heartbeat failed for clip job %s", job_id, exc_info=True)

    async def _cancel_heartbeat(self, task: asyncio.Task[None]) -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _stale_job_sweeper(self) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                async with sessionmaker() as session:
                    result = await job_service.sweep_stale_jobs(
                        session,
                        stale_timeout_s=self._settings.job_stale_timeout_s,
                        max_attempts=self._settings.job_max_attempts,
                    )
                if result.requeued or result.failed:
                    logger.warning(
                        "stale clip job sweep requeued=%s failed=%s",
                        len(result.requeued),
                        len(result.failed),
                    )
                # Tell the orchestrator about jobs the sweeper gave up on so it can
                # fail the video immediately instead of waiting out its backstop.
                for job_id in result.failed:
                    await publish_clip_result(
                        job_id, "failed", error="clip worker heartbeat stale; gave up"
                    )
            except Exception:  # noqa: BLE001
                logger.exception("stale clip job sweeper error")
            await asyncio.sleep(self._settings.job_stale_sweep_interval_s)

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
                    heartbeat = asyncio.create_task(
                        self._heartbeat_job(job.job_id), name=f"clip-heartbeat-{job.job_id}"
                    )
                    try:
                        # run_job opens its own per-item sessions for concurrent
                        # processing; the claim/mark session here stays dedicated
                        # to job-row bookkeeping. The deadline stops a hung item
                        # (slow source / slowloris preview / stuck embed) from
                        # freezing the single worker — and stays below
                        # job_running_timeout_s so it fails rather than being
                        # requeued as an orphan and retried forever.
                        results = await asyncio.wait_for(
                            run_job(
                                sessionmaker,
                                self._embedder,
                                self._settings,
                                items,
                                credentials,
                                options,
                                embed_lock=self._embed_lock,
                            ),
                            timeout=self._settings.job_deadline_s,
                        )
                        await job_service.mark_job_done(session, job.job_id, results)
                        await publish_clip_result(
                            job.job_id, "done", items=results
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        logger.error(
                            "job %s exceeded deadline %ss",
                            job.job_id,
                            self._settings.job_deadline_s,
                        )
                        error = f"job exceeded {self._settings.job_deadline_s:.0f}s deadline"
                        await job_service.mark_job_failed(session, job.job_id, error)
                        await publish_clip_result(job.job_id, "failed", error=error)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("job %s failed", job.job_id)
                        await job_service.mark_job_failed(session, job.job_id, str(exc))
                        await publish_clip_result(job.job_id, "failed", error=str(exc))
                    finally:
                        await self._cancel_heartbeat(heartbeat)
            except Exception:  # noqa: BLE001
                logger.exception("worker loop error")
                await asyncio.sleep(self._settings.worker_poll_interval_s)
