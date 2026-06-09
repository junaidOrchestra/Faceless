"""FastAPI entrypoint for the faceless-video testing suite backend.

Takes YouTube links, drives the orchestrator pipeline to completion for each,
times every step, and serves the finished MP4s back to the UI.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .beats import enrich_beats
from .config import get_settings
from .models import BatchRequest, Job, Store
from .orchestrator_client import OrchestratorClient
from .pipeline import run_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("testing-suite")

settings = get_settings()
store = Store()

# Vibe slugs must match orchestrator/app/vibes.py (and seemless/lib/vibes.ts).
VIBES = [
    {"id": "space", "label": "Space & Cosmos"},
    {"id": "forest", "label": "Forest & Woods"},
    {"id": "ocean", "label": "Ocean & Underwater"},
    {"id": "mountains", "label": "Mountains & Peaks"},
    {"id": "desert", "label": "Desert & Dunes"},
    {"id": "rain", "label": "Rain & Storm"},
    {"id": "city_nights", "label": "City Nights & Urban"},
    {"id": "aerial", "label": "Aerial & Drone"},
    {"id": "wildlife", "label": "Wildlife & Animals"},
    {"id": "sky", "label": "Sky, Clouds & Sunset"},
    {"id": "snow", "label": "Snow & Winter"},
    {"id": "abstract", "label": "Abstract & Light"},
]

# Aspect choices -> orchestrator format strings (see orchestrator/app/formats.py).
FORMATS = [
    {"id": "youtube", "label": "16:9 — YouTube (landscape)"},
    {"id": "tiktok", "label": "9:16 — Shorts / TikTok (portrait)"},
    {"id": "instagram_post", "label": "1:1 — Square"},
]

QUALITIES = [
    {"id": "sd", "label": "SD (fastest)"},
    {"id": "hd", "label": "HD (default)"},
    {"id": "max", "label": "Max (slowest)"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.work_dir).mkdir(parents=True, exist_ok=True)
    app.state.http = httpx.AsyncClient(timeout=settings.http_timeout_s)
    app.state.semaphore = asyncio.Semaphore(settings.max_concurrency)
    app.state.tasks = set()
    logger.info("orchestrator=%s concurrency=%s", settings.orchestrator_url, settings.max_concurrency)
    try:
        yield
    finally:
        for t in list(app.state.tasks):
            t.cancel()
        await app.state.http.aclose()


app = FastAPI(title="Faceless Video Testing Suite", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "orchestrator": settings.orchestrator_url}


@app.get("/api/config")
async def config() -> dict:
    return {
        "vibes": VIBES,
        "formats": FORMATS,
        "qualities": QUALITIES,
        "orchestrator_url": settings.orchestrator_url,
    }


@app.post("/api/uploads")
async def upload_audio(files: list[UploadFile] = File(...)) -> dict:
    """Save uploaded audio/video files; returns ids to reference in a batch."""
    uploads_dir = Path(settings.work_dir) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        upload_id = uuid.uuid4().hex[:12]
        suffix = Path(f.filename or "").suffix or ".bin"
        dest = uploads_dir / f"{upload_id}{suffix}"
        size = 0
        with dest.open("wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
                size += len(chunk)
        store.add_upload(upload_id, str(dest), f.filename or f"{upload_id}{suffix}", size)
        saved.append({"upload_id": upload_id, "filename": f.filename, "size": size})
    return {"uploads": saved}


@app.post("/api/batches")
async def create_batch(req: BatchRequest) -> dict:
    videos = [v for v in req.videos if (v.url and v.url.strip()) or v.upload_id]
    if not videos:
        raise HTTPException(
            status_code=400, detail="Provide at least one YouTube URL or uploaded file."
        )

    batch = store.new_batch()
    for v in videos:
        common = dict(
            id=uuid.uuid4().hex[:12],
            theme_mode=v.theme_mode,
            vibe=v.vibe if v.theme_mode == "vibe" else None,
            video_format=v.video_format,
            quality=v.quality,
            subtitles=v.subtitles,
        )
        if v.upload_id:
            up = store.get_upload(v.upload_id)
            if up is None:
                raise HTTPException(status_code=400, detail=f"Unknown upload {v.upload_id}.")
            job = Job(
                source_type="upload",
                upload_path=up["path"],
                upload_filename=up["filename"],
                **common,
            )
        else:
            job = Job(source_type="youtube", url=(v.url or "").strip(), **common)
        store.add_job(job, batch)
        task = asyncio.create_task(
            run_job(job, settings, app.state.http, app.state.semaphore)
        )
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)

    return store.batch_dict(batch)


@app.get("/api/batches/{batch_id}")
async def get_batch(batch_id: str) -> dict:
    batch = store.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Unknown batch.")
    return store.batch_dict(batch)


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/beats")
async def get_job_beats(job_id: str) -> dict:
    """Per-beat breakdown: keywords, visual type, and routed clip-server sources."""
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")
    if not job.orchestrator_job_id:
        return {"job_id": job_id, "ready": False, "beats": []}
    client = OrchestratorClient(settings, app.state.http)
    raw = await client.get_beats(job.orchestrator_job_id)
    beats = enrich_beats(raw, settings)
    # Summary counts by coarse type bucket.
    summary = {"personality": 0, "event": 0, "general": 0}
    for b in beats:
        summary[b["type_bucket"]] = summary.get(b["type_bucket"], 0) + 1
    return {"job_id": job_id, "ready": len(beats) > 0, "beats": beats, "summary": summary}


@app.get("/api/jobs/{job_id}/video")
async def get_job_video(job_id: str):
    job = store.get_job(job_id)
    if job is None or not job.has_video:
        raise HTTPException(status_code=404, detail="Video not ready.")
    path = Path(settings.output_dir) / f"{job_id}.mp4"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rendered file missing.")
    safe_title = "".join(c for c in (job.title or job_id) if c.isalnum() or c in " -_")[:60].strip()
    filename = f"{safe_title or job_id}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=filename)
