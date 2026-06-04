"""FastAPI entrypoint for the orchestrator."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .auth import require_auth
from .clip_client.factory import build_clip_client
from .config import Settings, get_settings
from .dependencies import SessionDep, SettingsDep
from .llm.factory import build_llm
from .logging_config import configure_logging, request_id_var
from .renderer.factory import build_renderer
from .schemas import CreateVideoResponse, ErrorResponse, HealthResponse, VideoCredentials, VideoStatusResponse
from .services import video_jobs as job_service
from .transcriber.factory import build_transcriber
from .worker import VideoWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    transcriber = build_transcriber(settings, force_stub=settings.llm_provider == "stub")
    llm = build_llm(settings)
    clip_client = build_clip_client(settings)
    renderer = build_renderer(settings)
    worker = VideoWorker(settings, transcriber, llm, clip_client, renderer)
    app.state.worker = worker
    await worker.start()
    logger.info("Orchestrator started (version=%s)", __version__)
    try:
        yield
    finally:
        await worker.stop()


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
) -> CreateVideoResponse:
    import json

    import httpx

    if audio is None and not audio_url:
        raise HTTPException(status_code=400, detail="Provide audio file or audio_url.")

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

    payload = {
        "sources": parsed_sources,
        "credentials": VideoCredentials(pexels=pexels_key).model_dump(),
    }
    await job_service.create_video_job(
        session,
        job_id,
        settings.default_user_id,
        str(audio_path),
        payload,
    )
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


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)
