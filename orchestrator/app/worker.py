"""Background worker for durable video jobs."""

from __future__ import annotations

import asyncio
import logging

from .clip_client.base import ClipClient
from .config import Settings
from .db import get_sessionmaker
from .llm.base import LLMProvider
from .pipeline import run_video_pipeline
from .renderer.base import Renderer
from .services import video_jobs as job_service
from .transcriber.base import Transcriber

logger = logging.getLogger(__name__)


class VideoWorker:
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
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="video-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def _loop(self) -> None:
        sessionmaker = get_sessionmaker()
        while not self._stop.is_set():
            try:
                async with sessionmaker() as session:
                    job = await job_service.claim_next_video_job(
                        session, self._settings.job_running_timeout_s
                    )
                    if job is None:
                        await asyncio.sleep(self._settings.worker_poll_interval_s)
                        continue
                    if not job.audio_path:
                        await job_service.mark_failed(session, job.id, "Missing audio_path.")
                        continue
                    try:
                        result_url = await run_video_pipeline(
                            session,
                            self._settings,
                            job.id,
                            job.audio_path,
                            job.payload or {},
                            transcriber=self._transcriber,
                            llm=self._llm,
                            clip_client=self._clip_client,
                            renderer=self._renderer,
                        )
                        await job_service.mark_done(session, job.id, result_url)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("video job %s failed", job.id)
                        await job_service.mark_failed(session, job.id, str(exc))
            except Exception:  # noqa: BLE001
                logger.exception("video worker loop error")
                await asyncio.sleep(self._settings.worker_poll_interval_s)
