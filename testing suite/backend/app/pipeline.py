"""End-to-end runner for a single video job.

Walks one YouTube URL through the full orchestrator pipeline with no human in
the loop, timing every step. The default selected candidate (clip/photo) for
each beat is used — we never override picks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx

from .config import Settings
from .models import Job
from .orchestrator_client import OrchestratorClient, OrchestratorError
from .uploads import prepare_uploaded_audio
from .youtube import fetch_audio

logger = logging.getLogger(__name__)

# Orchestrator statuses, in pipeline order, used to know when a stage finished.
_TRANSCRIBE_DONE = {"transcribed", "llm", "awaiting_clip", "ready", "render_queued", "rendering", "done"}
_CLIP_DONE = {"ready", "render_queued", "rendering", "done"}
_RENDER_DONE = {"done"}


class _StepTimer:
    """Marks a job step running on enter and done/failed on exit."""

    def __init__(self, job: Job, key: str) -> None:
        self.job = job
        self.step = job.step(key)

    def __enter__(self) -> "_StepTimer":
        self.step.status = "running"
        self.step.started_at = time.time()
        self.job.log(f"-> {self.step.label}")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.step.ended_at = time.time()
        if exc_type is None:
            self.step.status = "done"
            self.job.log(f"   done in {self.step.duration_s}s")
        else:
            self.step.status = "failed"
            self.step.detail = str(exc)
            self.job.log(f"   FAILED: {exc}")
        return False  # never swallow


def _theme(job: Job) -> dict:
    if job.theme_mode == "vibe" and job.vibe:
        return {"mode": "vibe", "vibe": job.vibe}
    return {"mode": "script", "vibe": None}


async def _poll_until(
    client: OrchestratorClient,
    job: Job,
    target: set[str],
    settings: Settings,
) -> dict:
    """Poll job status until it reaches a target status or fails/times out."""
    deadline = time.time() + settings.stage_timeout_s
    last = None
    while True:
        status = await client.get_status(job.orchestrator_job_id or "")
        s = status.get("status")
        if s != last:
            job.log(f"   status={s} progress={status.get('progress')}")
            last = s
        if s == "failed":
            raise OrchestratorError(status.get("error") or "orchestrator job failed")
        if s in target:
            return status
        if time.time() > deadline:
            raise OrchestratorError(f"timed out waiting (last status={s})")
        await asyncio.sleep(settings.poll_interval_s)


async def run_job(
    job: Job,
    settings: Settings,
    http: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        job.status = "running"
        client = OrchestratorClient(settings, http)
        work_dir = Path(settings.work_dir) / job.id
        try:
            # 1. Get audio: download from YouTube, or normalize an upload
            #    (both produce the same small mono MP3). Blocking -> thread.
            with _StepTimer(job, "fetch_audio") as t:
                if job.source_type == "upload":
                    fetched = await asyncio.to_thread(
                        prepare_uploaded_audio,
                        job.upload_path,
                        str(work_dir),
                        settings,
                        job.upload_filename or "audio",
                    )
                else:
                    fetched = await asyncio.to_thread(
                        fetch_audio, job.url, str(work_dir), settings
                    )
                job.title = fetched.title
                job.duration_s = fetched.duration_s
                t.step.detail = (
                    f"{fetched.title} · {round(fetched.duration_s)}s · "
                    f"{fetched.size_bytes // 1024} KB"
                )

            # 2. Submit to orchestrator (no format -> pauses at transcribed).
            with _StepTimer(job, "create"):
                job.orchestrator_job_id = await client.create_video(fetched.path)
                job.step("create").detail = job.orchestrator_job_id

            # 3. Wait for transcription.
            with _StepTimer(job, "transcribe"):
                await _poll_until(client, job, _TRANSCRIBE_DONE, settings)

            # 4. Supply output choices + content theme -> starts clip search.
            with _StepTimer(job, "prepare") as t:
                await client.prepare(
                    job.orchestrator_job_id,
                    video_format=job.video_format,
                    quality=job.quality,
                    subtitles=job.subtitles,
                    theme=_theme(job),
                )
                th = _theme(job)
                t.step.detail = (
                    f"{job.video_format} · {job.quality} · subs={job.subtitles} · "
                    f"theme={th['mode']}{('/' + th['vibe']) if th['vibe'] else ''}"
                )

            # 5. Wait for clip search to finish (job reaches 'ready').
            with _StepTimer(job, "clip_search") as t:
                await _poll_until(client, job, _CLIP_DONE, settings)
                beats = await client.get_beats(job.orchestrator_job_id)
                job.beats = len(beats)
                t.step.detail = f"{len(beats)} beats"

            # 6. Render with default selected candidates, then wait for completion.
            with _StepTimer(job, "render"):
                await client.render(job.orchestrator_job_id)
                await _poll_until(client, job, _RENDER_DONE, settings)

            # 7. Download the finished MP4 to the shared output volume.
            with _StepTimer(job, "download") as t:
                dest = Path(settings.output_dir) / f"{job.id}.mp4"
                size = await client.download(job.orchestrator_job_id, str(dest))
                job.output_size_bytes = size
                job.has_video = True
                t.step.detail = f"{size // (1024 * 1024)} MB"

            job.status = "done"
            job.log(f"ALL DONE in {job.total_duration_s}s")
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "failed"
            job.error = str(exc)
            logger.exception("job %s failed", job.id)
        finally:
            # Tidy the temp audio; keep the rendered mp4 in OUTPUT_DIR.
            try:
                if work_dir.exists():
                    for f in work_dir.iterdir():
                        f.unlink(missing_ok=True)
                    work_dir.rmdir()
            except OSError:
                pass
