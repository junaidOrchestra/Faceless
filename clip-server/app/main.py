"""FastAPI application entrypoint for the CLIP server."""

from __future__ import annotations

import asyncio
import logging
import os
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


def _configure_torch_threads(settings: Settings) -> None:
    """Apply CPU thread limits before sentence-transformers imports torch."""

    threads = int(settings.clip_torch_threads or 0)
    interop = int(settings.clip_torch_interop_threads or 0)
    if threads > 0:
        os.environ.setdefault("OMP_NUM_THREADS", str(threads))
        os.environ.setdefault("MKL_NUM_THREADS", str(threads))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(threads))
    try:
        import torch

        if threads > 0:
            torch.set_num_threads(threads)
        if interop > 0:
            torch.set_num_interop_threads(interop)
    except Exception as exc:  # noqa: BLE001 - thread tuning must not block startup
        logger.warning("could not configure torch thread limits: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load CLIP once, start the durable job worker, clean up on shutdown."""

    settings = get_settings()
    configure_logging(settings.log_level)
    _configure_torch_threads(settings)
    embed_lock = asyncio.Lock()
    embedder = ClipEmbedder(
        settings.clip_model_name,
        device=settings.clip_device,
        text_cache_size=settings.text_embed_cache_size,
    )
    app.state.embedder = embedder
    app.state.embed_lock = embed_lock
    worker = JobWorker(settings, embedder, embed_lock=embed_lock)
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
    # Source API keys come from THIS service's environment, not the request: the
    # orchestrator no longer sends keys over the wire. Any key the caller does
    # send still wins (back-compat), but normally these env fallbacks supply
    # them. The per-source guard only runs a key-requiring source when its
    # credential is present in this dict.
    credentials = body.credentials.model_dump()
    if not credentials.get("pexels") and settings.pexels_api_key:
        credentials["pexels"] = settings.pexels_api_key
    if not credentials.get("pixabay") and settings.pixabay_api_key:
        credentials["pixabay"] = settings.pixabay_api_key
    if not credentials.get("flickr") and settings.flickr_api_key:
        credentials["flickr"] = settings.flickr_api_key
    try:
        await job_service.upsert_job(
            session,
            body.job_id,
            {
                "items": items_payload,
                "credentials": credentials,
                "options": body.options.model_dump(exclude_none=True),
            },
        )
    except Exception as exc:  # noqa: BLE001 - surface the real cause, not a blank 500
        # Most likely a DB connection/schema problem (the job row never persists).
        # Log the full traceback and return the error type so the orchestrator's
        # logs show *why* the submit failed instead of an opaque 500.
        logger.exception("failed to create job %s", body.job_id)
        raise HTTPException(
            status_code=500,
            detail=f"Could not persist job: {type(exc).__name__}: {exc}",
        ) from exc
    return CreateJobResponse(job_id=body.job_id)


@app.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    response_model_exclude_none=True,
    tags=["jobs"],
    summary="Poll job status and fetch results",
    description=(
        "While the job is queued/running, returns status only (no payload). On "
        "failure, returns the error. The ranked assets are returned ONLY once the "
        "whole job is complete (status=done) — never partial/mid-flight — and the "
        "job is pruned after that first successful read (fetch-once)."
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

    # Still working: report status only, never a (partial) payload.
    if job.status in ("queued", "running"):
        return JobStatusResponse(job_id=job.job_id, status=job.status)  # type: ignore[arg-type]

    # Failed: surface the error so the orchestrator can fail the video job.
    if job.status == "failed":
        return JobStatusResponse(
            job_id=job.job_id, status="failed", error=job.error or "CLIP job failed"
        )

    # Done: the complete ranked result is ready. Return it once, then prune.
    items = [JobItemResult.model_validate(row) for row in (job.items_result or [])]
    if getattr(request.app.state, "prune_on_fetch", True):
        logger.info(
            "job %s processed: %s",
            job_id,
            [item.get("keyword") for item in (job.items_input or {}).get("items", [])],
        )
        await job_service.prune_job(session, job_id)
    return JobStatusResponse(job_id=job.job_id, status="done", items=items)


@app.post(
    "/text-embed",
    response_model=TextEmbedResponse,
    tags=["embeddings"],
    summary="Embed texts with CLIP",
    description="Utility endpoint returning L2-normalized CLIP text vectors.",
    dependencies=[Depends(require_auth)],
)
async def text_embed(
    body: TextEmbedRequest,
    request: Request,
    embedder: EmbedderDep,
    settings: SettingsDep,
) -> TextEmbedResponse:
    if len(body.texts) > settings.max_text_embed_texts:
        raise HTTPException(status_code=400, detail="Too many texts.")
    embed_lock = getattr(request.app.state, "embed_lock", None)
    if embed_lock is None:
        embed_lock = asyncio.Lock()
        request.app.state.embed_lock = embed_lock
    async with embed_lock:
        vectors = await asyncio.to_thread(embedder.embed_texts, body.texts)
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
