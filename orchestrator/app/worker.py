"""Staged background workers for the video pipeline.

Instead of one worker running the whole pipeline per job, the pipeline is split
into independent stages, each with its own worker pool fed by a Redis queue:

* **transcribe** pool — ``transcribe:queue`` -> :func:`pipeline.stage_transcribe`,
  then enqueue onto ``llm:queue``.
* **llm** pool — ``llm:queue`` -> :func:`pipeline.stage_llm` (LLM + submit CLIP
  job), then move the job to ``awaiting_clip`` (or ``ready`` if nothing to
  search).
* **clip result consumer** (single task) — consumes finished clip-search results
  the clip-server publishes to the shared Redis ``clip_result`` queue, transforms
  each into durable editor state, and moves the job to ``ready``. (The in-process
  stub has no Redis publisher, so stub/local runs fall back to a **clip poller**
  that HTTP-polls the clip-server instead.)
* **render** pool — ``render:queue`` -> :func:`pipeline.stage_render`. Rendering
  is *not* automatic; the API enqueues a render request for a ``ready`` job.

Postgres remains the source of truth. On startup, jobs orphaned mid-stage are
reset to their pending status and the Redis queues are rebuilt from the DB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from . import pipeline
from . import queue as job_queue
from .clip_client.base import ClipClient
from .clip_client.schemas import ClipJobStatusResponse
from .clip_client.stub import StubClipClient
from .config import Settings
from .db import get_sessionmaker, safe_db_target
from .llm.base import LLMProvider
from .renderer.base import Renderer
from .services import credits as credit_service
from .services import projects as project_service
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
        # Clip-search result handling. With the real clip-server, results arrive
        # via the shared Redis result queue (the clip-server publishes; we
        # consume). The in-process stub has no Redis publisher, so fall back to
        # HTTP polling for local/stub runs and tests.
        if isinstance(self._clip_client, StubClipClient):
            self._tasks.append(asyncio.create_task(self._clip_poller(), name="clip-poller"))
            clip_mode = "clip poller (stub)"
        else:
            self._tasks.append(
                asyncio.create_task(self._clip_result_consumer(), name="clip-result-consumer")
            )
            clip_mode = "clip result consumer"
        self._tasks.append(asyncio.create_task(self._stale_job_sweeper(), name="stale-job-sweeper"))
        logger.info(
            "started pipeline workers (transcribe=%s llm=%s render=%s + %s + stale sweeper)",
            max(1, s.transcribe_concurrency),
            max(1, s.llm_concurrency),
            max(1, s.render_concurrency),
            clip_mode,
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
            # The clip-result queue's pending set can't be rebuilt from our DB
            # (messages originate in the clip-server). Re-deliver anything a prior
            # process claimed but didn't ack instead of dropping it.
            await job_queue.clip_result_queue.requeue_processing()
        except Exception:  # noqa: BLE001 - never block startup on reconcile
            logger.exception(
                "failed to reconcile job queues on startup (db=%s)", safe_db_target()
            )

    # -- generic stage consumer ------------------------------------------------

    async def _consume(self, queue: job_queue.RedisQueue, worker_id: int, handler) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                job_id = await queue.claim(self._settings.worker_queue_block_timeout_s)
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
        """Mark a job failed on a FRESH session (the failing op may have tainted it).

        For a failed *render* this also refunds any credits charged at render
        time (idempotent) and marks the linked project failed, so a user is never
        billed for a video that didn't ship.
        """

        logger.exception("job %s failed in %s stage", job_id, stage)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        async with sessionmaker() as fail_session:
            await job_service.mark_failed(fail_session, job_id, str(exc))
        if stage == "render":
            async with sessionmaker() as refund_session:
                await self._refund_render(refund_session, job_id)

    async def _refund_render(self, session, job_id: str) -> None:
        """Refund render credits and fail the project for a failed render (idempotent)."""

        job = await job_service.get_video_job(session, job_id)
        if job is None:
            return
        payload = job.payload or {}
        amount = int(payload.get("credits_charged") or 0)
        user_id = payload.get("charge_user_id")
        project_id = payload.get("project_id") or job.project_id

        if amount > 0 and user_id and not payload.get("refunded"):
            try:
                refunded = await credit_service.refund_credits(
                    session, user_id, amount, project_id=project_id or job_id
                )
                if refunded:
                    new_payload = dict(payload)
                    new_payload["refunded"] = True
                    await job_service.update_payload(session, job_id, new_payload)
                    logger.info(
                        "refunded %s credit(s) to %s after failed render of %s",
                        amount,
                        user_id,
                        job_id,
                    )
            except Exception:  # noqa: BLE001 - never let a refund failure mask the job failure
                logger.exception("failed to refund credits for job %s", job_id)

        if project_id:
            try:
                await project_service.update_project(session, project_id, status="failed")
            except Exception:  # noqa: BLE001
                logger.warning("could not mark project %s failed", project_id, exc_info=True)

    async def _heartbeat_job(self, sessionmaker, job_id: str, active_status: str) -> None:
        """Refresh an active job heartbeat until the stage finishes."""

        while not self._stop.is_set():
            await asyncio.sleep(self._settings.job_heartbeat_interval_s)
            try:
                async with sessionmaker() as session:
                    refreshed = await job_service.heartbeat_job(session, job_id, active_status)
                if not refreshed:
                    return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - heartbeat failure should not kill the stage
                logger.warning("heartbeat failed for job %s (%s)", job_id, active_status, exc_info=True)

    async def _cancel_heartbeat(self, task: asyncio.Task[None]) -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _enqueue_recovered_jobs(self, requeued: dict[str, list[str]]) -> None:
        for status, job_ids in requeued.items():
            queue = {
                "queued": job_queue.transcribe_queue,
                "transcribed": job_queue.llm_queue,
                "render_queued": job_queue.render_queue,
            }.get(status)
            if queue is None:
                continue
            for job_id in job_ids:
                await queue.enqueue(job_id)

    async def _stale_job_sweeper(self) -> None:
        """Periodically recover active jobs whose worker heartbeat stopped."""

        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                async with sessionmaker() as session:
                    result = await job_service.sweep_stale_active_jobs(
                        session,
                        stale_timeout_s=self._settings.job_stale_timeout_s,
                        max_attempts=self._settings.job_max_attempts,
                    )
                await self._enqueue_recovered_jobs(result.requeued)
                recovered = {k: len(v) for k, v in result.requeued.items() if v}
                if recovered or result.failed:
                    logger.warning(
                        "stale job sweep recovered=%s failed=%s",
                        recovered,
                        len(result.failed),
                    )
            except Exception:  # noqa: BLE001
                logger.exception("stale job sweeper error (db=%s)", safe_db_target())
            await asyncio.sleep(self._settings.job_stale_sweep_interval_s)

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
            heartbeat = asyncio.create_task(
                self._heartbeat_job(sessionmaker, job_id, "transcribing"),
                name=f"heartbeat-transcribing-{job_id}",
            )
            try:
                await asyncio.wait_for(
                    pipeline.stage_transcribe(
                        session,
                        self._settings,
                        job_id,
                        job.audio_path,
                        job.payload or {},
                        transcriber=self._transcriber,
                    ),
                    timeout=self._settings.transcribe_timeout_s,
                )
                logger.info(
                    "stage transcribe for job %s finished in %.2fs",
                    job_id,
                    time.monotonic() - started,
                )
                await job_service.advance(session, job_id, "transcribed")
                # Gate: only continue into the LLM + clip-search stage once the
                # caller has committed the output shape (format/quality). A job
                # submitted without a format pauses here until POST /prepare sets
                # ``prepared`` (re-read fresh: /prepare may have just set it while
                # we were transcribing).
                await session.refresh(job)
                if (job.payload or {}).get("prepared"):
                    # Idempotent: POST /prepare may also be enqueueing this exact
                    # job right now (it re-reads status after flipping `prepared`).
                    # The SET NX guard ensures the clip search is dispatched once.
                    await job_queue.llm_queue.enqueue_once(job_id)
                else:
                    logger.info(
                        "job %s transcribed; awaiting /prepare before clip search", job_id
                    )
            except (asyncio.TimeoutError, TimeoutError):
                await self._fail(
                    sessionmaker,
                    session,
                    job_id,
                    "transcribe",
                    TimeoutError(
                        f"Transcription exceeded {self._settings.transcribe_timeout_s:.0f}s"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                await self._fail(sessionmaker, session, job_id, "transcribe", exc)
            finally:
                await self._cancel_heartbeat(heartbeat)

    async def _handle_llm(self, sessionmaker, job_id: str, worker_id: int) -> None:
        async with sessionmaker() as session:
            # Guard: a transcribed job may land on the llm queue via startup
            # reconcile before it has been prepared. Skip it (a later /prepare
            # re-enqueues) so the output-shape gate is never bypassed.
            existing = await job_service.get_video_job(session, job_id)
            if existing is None:
                return
            if existing.status == "transcribed" and not (existing.payload or {}).get(
                "prepared"
            ):
                logger.info("job %s on llm queue but not prepared; skipping", job_id)
                return
            job = await job_service.claim_for_stage(
                session, job_id, from_statuses=("transcribed", "llm"), to_status="llm"
            )
            if job is None:
                return
            logger.info("llm worker %s processing job %s", worker_id, job_id)
            started = time.monotonic()
            heartbeat = asyncio.create_task(
                self._heartbeat_job(sessionmaker, job_id, "llm"),
                name=f"heartbeat-llm-{job_id}",
            )
            try:
                submitted = await asyncio.wait_for(
                    pipeline.stage_llm(
                        session,
                        self._settings,
                        job_id,
                        job.payload or {},
                        llm=self._llm,
                        clip_client=self._clip_client,
                    ),
                    timeout=self._settings.llm_stage_timeout_s,
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
            except (asyncio.TimeoutError, TimeoutError):
                await self._fail(
                    sessionmaker,
                    session,
                    job_id,
                    "llm",
                    TimeoutError(
                        f"LLM stage exceeded {self._settings.llm_stage_timeout_s:.0f}s"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                await self._fail(sessionmaker, session, job_id, "llm", exc)
            finally:
                await self._cancel_heartbeat(heartbeat)

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
            heartbeat = asyncio.create_task(
                self._heartbeat_job(sessionmaker, job_id, "rendering"),
                name=f"heartbeat-rendering-{job_id}",
            )
            try:
                result_url = await asyncio.wait_for(
                    pipeline.stage_render(
                        session,
                        self._settings,
                        job_id,
                        job.audio_path,
                        job.payload or {},
                        renderer=self._renderer,
                    ),
                    timeout=self._settings.render_stage_timeout_s,
                )
                logger.info(
                    "stage render for job %s finished in %.2fs",
                    job_id,
                    time.monotonic() - started,
                )
                await job_service.mark_done(session, job_id, result_url)
                if job.project_id:
                    async with sessionmaker() as proj_session:
                        await project_service.update_project(
                            proj_session,
                            job.project_id,
                            status="done",
                            result_url=result_url,
                        )
            except (asyncio.TimeoutError, TimeoutError):
                await self._fail(
                    sessionmaker,
                    session,
                    job_id,
                    "render",
                    TimeoutError(
                        f"Render stage exceeded {self._settings.render_stage_timeout_s:.0f}s"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                await self._fail(sessionmaker, session, job_id, "render", exc)
            finally:
                await self._cancel_heartbeat(heartbeat)

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
                logger.exception("clip poller scan error (db=%s)", safe_db_target())
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

    # -- clip result consumer (Redis push from clip-server) --------------------

    async def _clip_result_consumer(self) -> None:
        """Consume finished clip-search results the clip-server publishes to Redis.

        Each message is a terminal :class:`ClipJobStatusResponse` envelope keyed
        by the clip job id (``<video_job_id>-clip``). We transform it into durable
        editor state via :func:`pipeline.apply_clip_result` and mark the job ready
        (or failed) — the same work the HTTP poller did, now event-driven.
        """

        sessionmaker = get_sessionmaker()
        queue = job_queue.clip_result_queue
        last_backstop = time.monotonic()
        while not self._stop.is_set():
            try:
                raw = await queue.claim(self._settings.worker_queue_block_timeout_s)
                if raw is not None:
                    try:
                        await self._handle_clip_result(sessionmaker, raw)
                    finally:
                        await queue.ack(raw)
                # A published result may never arrive (clip-server crash, Redis
                # flush). Periodically fail awaiting_clip jobs older than the cap
                # so they don't hang forever.
                now = time.monotonic()
                if now - last_backstop >= self._settings.clip_poll_scan_interval_s:
                    last_backstop = now
                    await self._clip_age_backstop(sessionmaker)
            except Exception:  # noqa: BLE001
                logger.exception("clip result consumer error (db=%s)", safe_db_target())
                await asyncio.sleep(self._settings.worker_poll_interval_s)

    async def _handle_clip_result(self, sessionmaker, raw: str) -> None:
        try:
            msg = json.loads(raw)
            status = ClipJobStatusResponse.model_validate(msg)
        except Exception:  # noqa: BLE001 - a malformed message must not wedge the queue
            logger.exception("dropping malformed clip result message")
            return

        clip_job_id = status.job_id or ""
        video_job_id = (
            clip_job_id[: -len("-clip")] if clip_job_id.endswith("-clip") else clip_job_id
        )

        async with sessionmaker() as session:
            job = await job_service.get_video_job(session, video_job_id)
            if job is None or job.status != "awaiting_clip":
                logger.info(
                    "ignoring clip result for %s (status=%s)",
                    video_job_id,
                    None if job is None else job.status,
                )
                return
            payload = job.payload or {}
            try:
                outcome = await pipeline.apply_clip_result(
                    session, self._settings, video_job_id, payload, status
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("clip result apply error for %s", video_job_id)
                try:
                    await session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                async with sessionmaker() as fail_session:
                    await job_service.mark_failed(fail_session, video_job_id, str(exc))
                return

        logger.info("clip result for job %s applied -> %s", video_job_id, outcome)

    async def _clip_age_backstop(self, sessionmaker) -> None:
        async with sessionmaker() as session:
            jobs = await job_service.list_awaiting_clip_jobs(session)
            stale = [(j.id, _age_seconds(j.created_at)) for j in jobs]
        for job_id, age in stale:
            if self._stop.is_set():
                break
            if age is not None and age > self._settings.clip_poll_max_age_s:
                self._clip_started.pop(job_id, None)
                async with sessionmaker() as fail_session:
                    await job_service.mark_failed(
                        fail_session, job_id, f"CLIP search timed out after {age:.0f}s"
                    )
