"""Staged background workers for the video pipeline.

Instead of one worker running the whole pipeline per job, the pipeline is split
into independent stages, each with its own worker pool fed by a Redis queue:

* **transcribe** pool — ``transcribe:queue`` -> :func:`pipeline.stage_transcribe`,
  then enqueue onto ``llm:queue``.
* **llm** pool — ``llm:queue`` -> :func:`pipeline.stage_llm` (LLM + submit CLIP
  job), then move the job to ``awaiting_clip`` (or ``ready`` if nothing to
  search).
* **clip poller** (single task) — periodically scans ``awaiting_clip`` jobs and
  polls the clip-server once each; on completion writes assignments and moves the
  job to ``ready``. A blocked clip job no longer ties up a worker slot.
* **render** pool — ``render:queue`` -> :func:`pipeline.stage_render`. Rendering
  is *not* automatic; the API enqueues a render request for a ``ready`` job.

Postgres remains the source of truth. On startup, jobs orphaned mid-stage are
reset to their pending status and the Redis queues are rebuilt from the DB.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from . import pipeline
from . import queue as job_queue
from .clip_client.base import ClipClient
from .config import Settings
from .db import get_sessionmaker
from .llm.base import LLMProvider
from .renderer.base import Renderer
from .services import video_jobs as job_service
from .transcriber.base import Transcriber

logger = logging.getLogger(__name__)


def _age_seconds(created_at: datetime | None) -> float | None:
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds()


class PipelineWorkers:
    """Owns every stage worker pool plus the single clip poller."""

    def __init__(
        self,
        settings: Settings,
        transcriber: Transcriber,
        llm: LLMProvider,
        clip_client: ClipClient,
        renderer: Renderer,
    ) -> None:
        self._settings = settings
        self._transcriber = transcriber
        self._llm = llm
        self._clip_client = clip_client
        self._renderer = renderer
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        # Wall-clock start of the clip-search wait per job (set on first poll),
        # used to log how long the clip step took once it finishes.
        self._clip_started: dict[str, float] = {}

    async def start(self) -> None:
        if self._tasks:
            return
        await self._reconcile_on_startup()
        s = self._settings

        for n in range(max(1, s.transcribe_concurrency)):
            self._tasks.append(
                asyncio.create_task(
                    self._consume(job_queue.transcribe_queue, n, self._handle_transcribe),
                    name=f"transcribe-{n}",
                )
            )
        for n in range(max(1, s.llm_concurrency)):
            self._tasks.append(
                asyncio.create_task(
                    self._consume(job_queue.llm_queue, n, self._handle_llm),
                    name=f"llm-{n}",
                )
            )
        for n in range(max(1, s.render_concurrency)):
            self._tasks.append(
                asyncio.create_task(
                    self._consume(job_queue.render_queue, n, self._handle_render),
                    name=f"render-{n}",
                )
            )
        self._tasks.append(asyncio.create_task(self._clip_poller(), name="clip-poller"))
        logger.info(
            "started pipeline workers (transcribe=%s llm=%s render=%s + 1 clip poller)",
            max(1, s.transcribe_concurrency),
            max(1, s.llm_concurrency),
            max(1, s.render_concurrency),
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks = []

    async def _reconcile_on_startup(self) -> None:
        """Requeue jobs orphaned mid-stage and rebuild the Redis queues from the DB."""

        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                resets = await job_service.reset_orphans(session)
                if any(resets.values()):
                    logger.info("reset orphaned jobs on startup: %s", resets)
                transcribe_ids = await job_service.list_job_ids_by_status(session, "queued")
                llm_ids = await job_service.list_job_ids_by_status(session, "transcribed")
                render_ids = await job_service.list_job_ids_by_status(session, "render_queued")
            await job_queue.transcribe_queue.rebuild(transcribe_ids)
            await job_queue.llm_queue.rebuild(llm_ids)
            await job_queue.render_queue.rebuild(render_ids)
        except Exception:  # noqa: BLE001 - never block startup on reconcile
            logger.exception("failed to reconcile job queues on startup")

    # -- generic stage consumer ------------------------------------------------

    async def _consume(self, queue: job_queue.RedisQueue, worker_id: int, handler) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                job_id = await queue.claim(self._settings.worker_poll_interval_s)
                if job_id is None:
                    continue
                try:
                    await handler(sessionmaker, job_id, worker_id)
                finally:
                    await queue.ack(job_id)
            except Exception:  # noqa: BLE001
                logger.exception("%s worker %s loop error", queue.name, worker_id)
                await asyncio.sleep(self._settings.worker_poll_interval_s)

    async def _fail(
        self, sessionmaker, session, job_id: str, stage: str, exc: BaseException
    ) -> None:
        """Mark a job failed on a FRESH session (the failing op may have tainted it)."""

        logger.exception("job %s failed in %s stage", job_id, stage)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        async with sessionmaker() as fail_session:
            await job_service.mark_failed(fail_session, job_id, str(exc))

    # -- stage handlers --------------------------------------------------------

    async def _handle_transcribe(self, sessionmaker, job_id: str, worker_id: int) -> None:
        async with sessionmaker() as session:
            job = await job_service.claim_for_stage(
                session, job_id, from_statuses=("queued", "transcribing"), to_status="transcribing"
            )
            if job is None:
                return
            if not job.audio_path:
                await job_service.mark_failed(session, job_id, "Missing audio_path.")
                return
            logger.info("transcribe worker %s processing job %s", worker_id, job_id)
            started = time.monotonic()
            try:
                await pipeline.stage_transcribe(
                    session,
                    self._settings,
                    job_id,
                    job.audio_path,
                    job.payload or {},
                    transcriber=self._transcriber,
                )
                logger.info(
                    "stage transcribe for job %s finished in %.2fs",
                    job_id,
                    time.monotonic() - started,
                )
                await job_service.advance(session, job_id, "transcribed")
                await job_queue.llm_queue.enqueue(job_id)
            except Exception as exc:  # noqa: BLE001
                await self._fail(sessionmaker, session, job_id, "transcribe", exc)

    async def _handle_llm(self, sessionmaker, job_id: str, worker_id: int) -> None:
        async with sessionmaker() as session:
            job = await job_service.claim_for_stage(
                session, job_id, from_statuses=("transcribed", "llm"), to_status="llm"
            )
            if job is None:
                return
            logger.info("llm worker %s processing job %s", worker_id, job_id)
            started = time.monotonic()
            try:
                submitted = await pipeline.stage_llm(
                    session,
                    self._settings,
                    job_id,
                    job.payload or {},
                    llm=self._llm,
                    clip_client=self._clip_client,
                )
                logger.info(
                    "stage llm for job %s finished in %.2fs",
                    job_id,
                    time.monotonic() - started,
                )
                if submitted:
                    # The clip poller takes over from awaiting_clip (no queue).
                    await job_service.advance(session, job_id, "awaiting_clip")
                else:
                    await job_service.advance(session, job_id, "ready", progress="ready")
            except Exception as exc:  # noqa: BLE001
                await self._fail(sessionmaker, session, job_id, "llm", exc)

    async def _handle_render(self, sessionmaker, job_id: str, worker_id: int) -> None:
        async with sessionmaker() as session:
            job = await job_service.claim_for_stage(
                session, job_id, from_statuses=("render_queued", "rendering"), to_status="rendering"
            )
            if job is None:
                return
            if not job.audio_path:
                await job_service.mark_failed(session, job_id, "Missing audio_path.")
                return
            logger.info("render worker %s processing job %s", worker_id, job_id)
            started = time.monotonic()
            try:
                result_url = await pipeline.stage_render(
                    session,
                    self._settings,
                    job_id,
                    job.audio_path,
                    job.payload or {},
                    renderer=self._renderer,
                )
                logger.info(
                    "stage render for job %s finished in %.2fs",
                    job_id,
                    time.monotonic() - started,
                )
                await job_service.mark_done(session, job_id, result_url)
            except Exception as exc:  # noqa: BLE001
                await self._fail(sessionmaker, session, job_id, "render", exc)

    # -- clip poller (single scanning task) ------------------------------------

    async def _clip_poller(self) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                async with sessionmaker() as session:
                    jobs = await job_service.list_awaiting_clip_jobs(session)
                    pending = [(j.id, j.payload or {}, j.created_at) for j in jobs]
                for job_id, payload, created_at in pending:
                    if self._stop.is_set():
                        break
                    await self._poll_one(sessionmaker, job_id, payload, created_at)
            except Exception:  # noqa: BLE001
                logger.exception("clip poller scan error")
            await asyncio.sleep(self._settings.clip_poll_scan_interval_s)

    async def _poll_one(self, sessionmaker, job_id: str, payload, created_at) -> None:
        # First time we poll this job marks the start of the clip-search wait.
        self._clip_started.setdefault(job_id, time.monotonic())
        async with sessionmaker() as session:
            try:
                outcome = await pipeline.poll_clip_job(
                    session, self._settings, job_id, payload, clip_client=self._clip_client
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("clip poll error for %s", job_id)
                self._clip_started.pop(job_id, None)
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                async with sessionmaker() as fail_session:
                    await job_service.mark_failed(fail_session, job_id, str(exc))
                return

        if outcome == "ready":
            elapsed = time.monotonic() - self._clip_started.pop(job_id, time.monotonic())
            logger.info(
                "stage clip_search for job %s finished in %.2fs -> ready", job_id, elapsed
            )
        elif outcome == "failed":
            self._clip_started.pop(job_id, None)
        elif outcome == "pending":
            age = _age_seconds(created_at)
            if age is not None and age > self._settings.clip_poll_max_age_s:
                self._clip_started.pop(job_id, None)
                async with sessionmaker() as fail_session:
                    await job_service.mark_failed(
                        fail_session, job_id, f"CLIP search timed out after {age:.0f}s"
                    )
