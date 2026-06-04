"""FastAPI application entrypoint for the CLIP server."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from . import __version__
from .auth import require_auth
from .config import Settings, get_settings
from .dependencies import EmbedderDep, SessionDep, SettingsDep
from .embedding.clip import ClipEmbedder
from .logging_config import configure_logging, request_id_var
from .schemas import (
    CreateJobRequest,
    CreateJobResponse,
    ErrorResponse,
    HealthResponse,
    JobItemResult,
    JobStatusResponse,
    TextEmbedRequest,
    TextEmbedResponse,
)
from .services import jobs as job_service
from .worker import JobWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load CLIP once, start the durable job worker, clean up on shutdown."""

    settings = get_settings()
    configure_logging(settings.log_level)
    embedder = ClipEmbedder(settings.clip_model_name, device=settings.clip_device)
    app.state.embedder = embedder
    worker = JobWorker(settings, embedder)
    app.state.worker = worker
    await worker.start()
    logger.info("CLIP server started (version=%s)", __version__)
    try:
        yield
    finally:
        await worker.stop()
        logger.info("CLIP server stopped.")


app = FastAPI(
    title="Faceless CLIP Server",
    description=(
        "Beat-agnostic keyword search primitive: given keywords, search stock sources, "
        "embed previews with CLIP, rank by cosine similarity, return assets. "
        "Jobs are durable (Postgres) with async submit-then-poll."
    ),
    version=__version__,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "jobs", "description": "Submit and poll durable ranking jobs."},
        {"name": "embeddings", "description": "CLIP text embedding utility."},
        {"name": "health", "description": "Liveness (no auth)."},
    ],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a request id to structured logs for the lifetime of the request."""

    token = request_id_var.set(request.headers.get("X-Request-Id", str(uuid.uuid4())))
    try:
        return await call_next(request)
    finally:
        request_id_var.reset(token)


def _validate_create_job(body: CreateJobRequest, settings: Settings) -> None:
    if len(body.items) > settings.max_items_per_job:
        raise HTTPException(status_code=400, detail="Too many items in job.")
    for item in body.items:
        if len(item.keyword) > settings.max_keyword_length:
            raise HTTPException(status_code=400, detail="Keyword too long.")
        if item.sources and len(item.sources) > settings.max_sources_per_item:
            raise HTTPException(status_code=400, detail="Too many sources on item.")


@app.post(
    "/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateJobResponse,
    tags=["jobs"],
    summary="Submit a batch keyword ranking job",
    description=(
        "Validates input, upserts a durable job (idempotent on job_id), and returns 202. "
        "Poll GET /jobs/{job_id} until status is done or failed."
    ),
    responses={400: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def create_job(
    body: CreateJobRequest,
    session: SessionDep,
    settings: SettingsDep,
) -> CreateJobResponse:
    _validate_create_job(body, settings)
    items_payload = [item.model_dump() for item in body.items]
    await job_service.upsert_job(
        session,
        body.job_id,
        {
            "items": items_payload,
            "credentials": body.credentials.model_dump(),
            "options": body.options.model_dump(exclude_none=True),
        },
    )
    return CreateJobResponse(job_id=body.job_id)


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    tags=["jobs"],
    summary="Poll job status and fetch results",
    description=(
        "While processing, status is queued or running. When done, ranked assets are "
        "included in this response. After a successful fetch the job is pruned."
    ),
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def get_job(
    job_id: str,
    request: Request,
    session: SessionDep,
) -> JobStatusResponse:
    job = await job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id.")

    items: list[JobItemResult] = []
    if job.items_result:
        items = [JobItemResult.model_validate(row) for row in job.items_result]

    response = JobStatusResponse(
        job_id=job.job_id,
        status=job.status,  # type: ignore[arg-type]
        items=items,
        error=job.error,
    )

    # Prune after the client successfully reads a terminal job (fetch-once semantics).
    if job.status == "done" and getattr(request.app.state, "prune_on_fetch", True):
        logger.info(
            "job %s processed: %s",
            job_id,
            [item.get("keyword") for item in (job.items_input or {}).get("items", [])],
        )
        await job_service.prune_job(session, job_id)

    return response


@app.post(
    "/text-embed",
    response_model=TextEmbedResponse,
    tags=["embeddings"],
    summary="Embed texts with CLIP",
    description="Utility endpoint returning L2-normalized CLIP text vectors.",
    dependencies=[Depends(require_auth)],
)
async def text_embed(body: TextEmbedRequest, embedder: EmbedderDep, settings: SettingsDep) -> TextEmbedResponse:
    vectors = embedder.embed_texts(body.texts)
    return TextEmbedResponse(
        embeddings=vectors.astype(float).tolist(),
        dim=settings.embedding_dim,
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["health"],
    summary="Liveness probe",
    description="No authentication required — used by Docker HEALTHCHECK and HF keep-alive.",
)
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)
