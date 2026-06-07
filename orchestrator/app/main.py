"""FastAPI entrypoint for the orchestrator."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from . import __version__
from . import queue as job_queue
from . import storage
from .auth import require_auth
from .clip_client.factory import build_clip_client
from .config import Settings, get_settings
from .dependencies import SessionDep, SettingsDep
from .llm.factory import build_llm
from .logging_config import configure_logging, request_id_var
from .renderer.factory import build_renderer
from .schemas import (
    BeatAssignmentOut,
    BeatCandidateOut,
    BeatOut,
    BeatsResponse,
    CreateVideoResponse,
    ErrorResponse,
    HealthResponse,
    VideoCredentials,
    VideoStatusResponse,
)
from .services import video_jobs as job_service
from .transcriber.factory import build_transcriber
from .worker import PipelineWorkers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    transcriber = build_transcriber(settings, force_stub=settings.llm_provider == "stub")
    llm = build_llm(settings)
    clip_client = build_clip_client(settings)
    renderer = build_renderer(settings)
    worker = PipelineWorkers(settings, transcriber, llm, clip_client, renderer)
    app.state.worker = worker
    await worker.start()
    logger.info("Orchestrator started (version=%s)", __version__)
    try:
        yield
    finally:
        await worker.stop()
        await job_queue.get_redis().aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Faceless Video Orchestrator",
        description=(
            "Beat-aware pipeline: narration audio → transcription → LLM keywords → "
            "CLIP server media → FFmpeg render. Durable Postgres jobs with submit-poll API."
        ),
        version=__version__,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "videos", "description": "Create and poll video generation jobs."},
            {"name": "health", "description": "Liveness (no auth)."},
        ],
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    )
    return application


app = create_app()


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    token = request_id_var.set(request.headers.get("X-Request-Id", str(uuid.uuid4())))
    try:
        return await call_next(request)
    finally:
        request_id_var.reset(token)


ALLOWED_AUDIO = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a"}
# Media download resolution tiers forwarded to the clip-server's source picks.
ALLOWED_QUALITY = {"sd", "hd", "max"}
DEFAULT_QUALITY = "hd"


@app.post(
    "/videos",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateVideoResponse,
    tags=["videos"],
    summary="Submit a narration audio video job",
    description=(
        "Upload an audio file (multipart) or pass audio_url in form fields. "
        "Returns 202 with video_job_id; poll GET /videos/{id} for progress."
    ),
    responses={400: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def create_video(
    session: SessionDep,
    settings: SettingsDep,
    audio: UploadFile | None = File(default=None, description="Narration audio file."),
    audio_url: str | None = Form(default=None, description="Optional URL to download audio."),
    sources: str | None = Form(default=None, description="JSON list of CLIP sources override."),
    pexels_key: str | None = Form(default=None, description="Pexels key forwarded to CLIP server."),
    pixabay_key: str | None = Form(default=None, description="Pixabay key forwarded to CLIP server."),
    video_format: str | None = Form(
        default=None,
        alias="format",
        description=(
            "Output format. One of: youtube (landscape 1920x1080, default), "
            "youtube_shorts, instagram_reels, tiktok (portrait 1080x1920), "
            "instagram_post (square 1080x1080)."
        ),
    ),
    quality: str | None = Form(
        default=None,
        description=(
            "Downloaded media resolution tier: 'sd' (~960px, fastest), "
            "'hd' (~1920px, default), or 'max' (largest/original — slowest)."
        ),
    ),
    subtitles: bool = Form(
        default=False,
        description=(
            "Burn per-beat narration captions into the video. Adds no extra "
            "render pass (folds into the existing per-segment encode)."
        ),
    ),
) -> CreateVideoResponse:
    import json

    import httpx

    from .formats import resolve_format

    if audio is None and not audio_url:
        raise HTTPException(status_code=400, detail="Provide audio file or audio_url.")

    try:
        fmt = resolve_format(video_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    quality_tier = (quality or DEFAULT_QUALITY).lower()
    if quality_tier not in ALLOWED_QUALITY:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid quality '{quality}'. Use one of: {sorted(ALLOWED_QUALITY)}.",
        )

    job_id = str(uuid.uuid4())
    work_dir = Path(settings.render_temp_dir) / "uploads" / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "narration.bin"

    if audio is not None:
        if audio.content_type and audio.content_type not in ALLOWED_AUDIO:
            raise HTTPException(status_code=400, detail="Unsupported audio content type.")
        data = await audio.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status_code=400, detail="Audio file too large.")
        # Preserve a safe extension for FFmpeg based on content type.
        ext = ".mp3" if "mpeg" in (audio.content_type or "") or "mp3" in (audio.content_type or "") else ".wav"
        audio_path = work_dir / f"narration{ext}"
        audio_path.write_bytes(data)
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(audio_url or "")
            response.raise_for_status()
            if len(response.content) > settings.max_upload_bytes:
                raise HTTPException(status_code=400, detail="Downloaded audio too large.")
            audio_path.write_bytes(response.content)

    parsed_sources = None
    if sources:
        try:
            parsed_sources = json.loads(sources)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid sources JSON.") from exc

    # Persist narration to durable storage (B2) so the on-demand render stage can
    # recover it after an ephemeral-/tmp restart. None in local mode.
    audio_object = await storage.publish_audio(settings, job_id, str(audio_path))

    payload = {
        "sources": parsed_sources,
        "credentials": VideoCredentials(pexels=pexels_key, pixabay=pixabay_key).model_dump(),
        "audio_object": audio_object,
        "quality": quality_tier,
        "subtitles": subtitles,
        "format": {
            "name": fmt.name,
            "orientation": fmt.orientation,
            "width": fmt.width,
            "height": fmt.height,
        },
    }
    await job_service.create_video_job(
        session,
        job_id,
        settings.default_user_id,
        str(audio_path),
        payload,
    )
    # Kick off the pipeline at the first stage: the transcribe worker pool picks
    # it up from here, then hands off through llm -> clip poll -> ready.
    await job_queue.transcribe_queue.enqueue(job_id)
    return CreateVideoResponse(video_job_id=job_id)


@app.get(
    "/videos/{video_job_id}",
    response_model=VideoStatusResponse,
    tags=["videos"],
    summary="Poll video job status",
    description="Returns queued/running/done/failed with optional result_url when complete.",
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def get_video(video_job_id: str, session: SessionDep) -> VideoStatusResponse:
    job = await job_service.get_video_job(session, video_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    return VideoStatusResponse(
        video_job_id=job.id,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        result_url=job.result_url,
        error=job.error,
    )


@app.get(
    "/videos/{video_job_id}/beats",
    response_model=BeatsResponse,
    tags=["videos"],
    summary="List a job's beats and their selected clips",
    description=(
        "Returns every beat of the job in order — transcript text, on-screen "
        "timing (start_s/end_s), the search queries chosen for it, and the media "
        "clip selected for it (if any). Populated once the job reaches the "
        "clip_search/rendering stages."
    ),
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def get_video_beats(video_job_id: str, session: SessionDep) -> BeatsResponse:
    job = await job_service.get_video_job(session, video_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    rows = await job_service.get_beats_with_assignments(session, video_job_id)
    beats = [
        BeatOut(
            index=beat.index,
            text=beat.text,
            start_s=beat.start_s,
            end_s=beat.end_s,
            queries=beat.queries,
            assignment=(
                BeatAssignmentOut(
                    platform=assignment.platform,
                    media_url=assignment.media_url,
                    preview_url=assignment.preview_url,
                    kind=assignment.kind,
                    score=assignment.score,
                    attribution=assignment.attribution,
                )
                if assignment is not None
                else None
            ),
            candidates=[
                BeatCandidateOut(**c)
                for c in (assignment.candidates or [])
            ]
            if assignment is not None
            else [],
        )
        for beat, assignment in rows
    ]
    return BeatsResponse(video_job_id=video_job_id, beats=beats)


# Statuses from which a render may be (re)started. Rendering is on demand so the
# caller can review /beats first; a finished job can also be re-rendered.
_RENDERABLE = {"ready", "done", "failed"}


@app.post(
    "/videos/{video_job_id}/render",
    response_model=VideoStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["videos"],
    summary="Request rendering of a prepared job",
    description=(
        "Enqueues the (already prepared) job for MP4 rendering. Rendering is not "
        "automatic: a job must first reach 'ready' (transcribe + LLM + clip search "
        "complete, beats/assignments stored — inspect them via GET /beats). Returns "
        "the job with status 'render_queued'; poll GET /videos/{id} for completion."
    ),
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def render_video(video_job_id: str, session: SessionDep) -> VideoStatusResponse:
    job = await job_service.get_video_job(session, video_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    if job.status not in _RENDERABLE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job is '{job.status}'; it can only be rendered once it reaches "
                f"'ready' (one of {sorted(_RENDERABLE)})."
            ),
        )
    await job_service.advance(session, video_job_id, "render_queued", progress="render_queued")
    await job_queue.render_queue.enqueue(video_job_id)
    return VideoStatusResponse(
        video_job_id=video_job_id,
        status="render_queued",  # type: ignore[arg-type]
        progress="render_queued",
        result_url=None,
        error=None,
    )


@app.get(
    "/videos/{video_job_id}/download",
    tags=["videos"],
    summary="Download the rendered video",
    description=(
        "Returns the finished MP4 for a done job. In local-storage mode the file is "
        "streamed directly; in B2 mode this redirects (307) to a downloadable B2 URL "
        "(presigned/time-limited for private buckets). 409 if the job isn't done yet."
    ),
    responses={
        307: {"description": "Redirect to the B2 download URL (cloud-storage mode)."},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
    dependencies=[Depends(require_auth)],
)
async def download_video(video_job_id: str, session: SessionDep, settings: SettingsDep):
    job = await job_service.get_video_job(session, video_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    if job.status != "done" or not job.result_url:
        raise HTTPException(
            status_code=409,
            detail=f"Video is not ready to download (status='{job.status}').",
        )

    # Local mode: stream the file off disk.
    if settings.storage_local:
        path = storage.local_result_path(settings, video_job_id)
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="Rendered file is no longer available on this server.",
            )
        return FileResponse(
            path, media_type="video/mp4", filename=f"{video_job_id}.mp4"
        )

    # Cloud mode: hand back a downloadable B2 URL (presigned for private buckets).
    url = await storage.b2_download_url(settings, video_job_id)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)
