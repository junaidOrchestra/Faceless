"""FastAPI entrypoint for the orchestrator."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response

from . import __version__
from . import media_validation
from . import queue as job_queue
from . import storage
from . import tiers
from . import vibes
from .clip_client.factory import build_clip_client
from .config import Settings, get_settings
from .dependencies import SessionDep, SettingsDep
from .identity import CurrentUserDep
from .llm.factory import build_llm
from .logging_config import configure_logging, request_id_var
from .ratelimit import enforce_rate_limit
from .renderer.factory import build_renderer
from .schemas import (
    BeatAssignmentOut,
    BeatCandidateOut,
    BeatOut,
    BeatsResponse,
    CreateVideoResponse,
    CreditsResponse,
    CreditTransactionOut,
    ErrorResponse,
    HealthResponse,
    MeResponse,
    PrepareRequest,
    ProjectOut,
    ProjectsResponse,
    RenderRequest,
    TierInfo,
    VideoCredentials,
    VideoStatusResponse,
)
from .services import credits as credit_service
from .services import projects as project_service
from .services import users as user_service
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
            {"name": "account", "description": "Authenticated user tier and credits."},
            {"name": "projects", "description": "Owner-scoped video projects."},
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


ALLOWED_AUDIO = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/webm",
    "audio/ogg",
}
# Video uploads / recordings: only the audio track is used (transcription runs
# through FFmpeg, which decodes the audio from the container). The product stays
# "faceless" — visuals come from stock clips, not the uploaded footage.
ALLOWED_VIDEO = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
    "video/ogg",
    "video/mpeg",
}
ALLOWED_MEDIA = ALLOWED_AUDIO | ALLOWED_VIDEO

# Content type -> on-disk extension so FFmpeg/whisper get a decodable container.
_MEDIA_EXT = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/webm": ".weba",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/ogg": ".ogv",
    "video/mpeg": ".mpg",
}
# Media download resolution tiers forwarded to the clip-server's source picks.
ALLOWED_QUALITY = {"sd", "hd", "max"}
DEFAULT_QUALITY = "hd"
_IO_CHUNK_SIZE = 1024 * 1024


async def _write_upload_stream(upload: UploadFile, path: Path, max_bytes: int) -> None:
    """Write an UploadFile to disk without buffering the whole file in memory."""

    total = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "wb") as fh:
            while True:
                chunk = await upload.read(_IO_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=400, detail="File too large.")
                fh.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def _download_to_path(
    client: httpx.AsyncClient,
    url: str,
    path: Path,
    max_bytes: int,
) -> None:
    """Stream a remote media URL to disk with the same upload size guard."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = 0
                if declared_size > max_bytes:
                    raise HTTPException(status_code=400, detail="Downloaded audio too large.")

            total = 0
            with open(path, "wb") as fh:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(status_code=400, detail="Downloaded audio too large.")
                    fh.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def _validate_or_reject(path: Path, settings: Settings) -> None:
    """Run magic-byte + ffprobe media validation; delete the file on rejection.

    A client fault (wrong/corrupt content, no audio) becomes a 400; any other
    failure (e.g. ffprobe missing) deletes the temp file and propagates so it
    surfaces as a 500 rather than masquerading as a bad upload.
    """

    try:
        await media_validation.validate_media_file(
            path,
            probe_timeout_s=settings.media_probe_timeout_s,
            require_audio=settings.media_require_audio_stream,
        )
    except media_validation.MediaValidationError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise


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
    responses={400: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
async def create_video(
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    audio: UploadFile | None = File(default=None, description="Narration audio file."),
    audio_url: str | None = Form(default=None, description="Optional URL to download audio."),
    sources: str | None = Form(default=None, description="JSON list of CLIP sources override."),
    pexels_key: str | None = Form(default=None, description="Pexels key forwarded to CLIP server."),
    pixabay_key: str | None = Form(default=None, description="Pixabay key forwarded to CLIP server."),
    flickr_key: str | None = Form(default=None, description="Flickr key forwarded to CLIP server."),
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

    # Rate-limit job creation / upload per user (protects whisper/ffmpeg + storage).
    await enforce_rate_limit(
        settings,
        bucket="create",
        identity=user.id,
        limit=settings.rate_limit_create_per_min,
    )

    # Per-tier abuse guards. Resolve the caller's tier (upserted at auth) and
    # enforce: a concurrent-job cap (no flooding the worker queues), a project
    # cap (bounds cumulative storage), and a daily upload cap (bounds upstream
    # transcribe/LLM/clip cost). The side-effect-free count checks run first so a
    # request rejected by them doesn't burn a daily slot. All run before any
    # bytes are written to disk.
    db_user = await user_service.get_user(session, user.id)
    tier = db_user.tier if db_user is not None else tiers.DEFAULT_TIER
    cfg = tiers.get_tier_config(tier)

    active_jobs = await job_service.count_active_jobs(session, user.id)
    if (violation := tiers.check_concurrency(tier, active_jobs)) is not None:
        raise HTTPException(status_code=409, detail=violation.message)

    project_count = await project_service.count_projects(session, user.id)
    if (violation := tiers.check_project_quota(tier, project_count)) is not None:
        raise HTTPException(status_code=409, detail=violation.message)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    await enforce_rate_limit(
        settings,
        bucket="create_daily",
        identity=f"{user.id}:{today}",
        limit=cfg.daily_uploads,
        window_s=86_400,
    )

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

    is_video_input = False
    if audio is not None:
        # Browsers tag recordings like "audio/webm;codecs=opus" — match on the
        # base type only.
        raw_ct = (audio.content_type or "").split(";")[0].strip().lower()
        if raw_ct and raw_ct not in ALLOWED_MEDIA:
            raise HTTPException(status_code=400, detail="Unsupported media content type.")
        # Preserve a safe extension for FFmpeg based on content type, falling
        # back to the uploaded filename's suffix. Works for audio and for video
        # (only the audio track is transcribed/served).
        ext = _MEDIA_EXT.get(raw_ct) or (Path(audio.filename or "").suffix.lower() or ".bin")
        audio_path = work_dir / f"narration{ext}"
        await _write_upload_stream(audio, audio_path, settings.max_upload_bytes)
        # A video upload (file or in-browser recording) doubles as visual source:
        # its footage, sliced to each beat's window, becomes the pre-selected clip
        # for that beat (with stock clips offered as swappable alternates).
        is_video_input = raw_ct in ALLOWED_VIDEO or ext in {
            ".mp4",
            ".webm",
            ".mov",
            ".mkv",
            ".ogv",
            ".mpg",
        }
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await _download_to_path(
                client,
                audio_url or "",
                audio_path,
                settings.max_upload_bytes,
            )

    # Defense-in-depth: the bytes are now on disk. Confirm they are genuinely a
    # decodable audio/video file with an audio track (magic-byte sniff + ffprobe)
    # BEFORE persisting to B2 or handing them to whisper/ffmpeg. Rejects disguised
    # payloads (e.g. an executable renamed .mp4) and corrupt/truncated media.
    await _validate_or_reject(audio_path, settings)

    parsed_sources = None
    if sources:
        try:
            parsed_sources = json.loads(sources)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid sources JSON.") from exc

    # Persist narration to durable storage (B2) so the on-demand render stage can
    # recover it after an ephemeral-/tmp restart. None in local mode.
    audio_object = await storage.publish_audio(settings, job_id, str(audio_path))

    # For a video input, the persisted file is also the visual source. Resolve a
    # fetchable URL the renderer (and editor) can pull the footage from: the
    # durable B2 object in cloud mode, or the local file path in local mode (the
    # renderer reads non-http paths straight from disk).
    source_video = None
    if is_video_input:
        if audio_object:
            try:
                source_url = await storage.object_download_url(settings, audio_object)
            except Exception:  # noqa: BLE001 - fall back to local path if B2 URL fails
                logger.exception("could not resolve source-video URL for job %s", job_id)
                source_url = str(audio_path)
        else:
            source_url = str(audio_path)
        source_video = {"url": source_url, "kind": "video"}

    payload = {
        "sources": parsed_sources,
        "credentials": VideoCredentials(
            pexels=pexels_key, pixabay=pixabay_key, flickr=flickr_key
        ).model_dump(),
        "audio_object": audio_object,
        "source_video": source_video,
        # Default content theme; the divided flow's POST /prepare may switch this
        # to a vibe before the clip search runs.
        "theme": {"mode": "script", "vibe": None},
        "quality": quality_tier,
        "subtitles": subtitles,
        "format": {
            "name": fmt.name,
            "orientation": fmt.orientation,
            "width": fmt.width,
            "height": fmt.height,
        },
        # Gate the clip search on the output shape. Passing an explicit ``format``
        # opts into the legacy one-shot behavior (transcribe straight through to
        # clip search). Omitting it pauses the job at ``transcribed`` until
        # POST /videos/{id}/prepare supplies the choices (review-beats-first flow).
        "prepared": video_format is not None,
    }
    # One project per video, owned by the caller. The job id doubles as the
    # project id (1:1) so the result/ownership lookups share a key.
    input_type = "video_file" if is_video_input else "audio_file"
    title = (audio.filename if audio is not None else audio_url) or "Untitled video"
    await project_service.create_project(
        session,
        job_id,
        user.id,
        title=title[:200],
        input_type=input_type,
        status="processing",
    )
    await job_service.create_video_job(
        session,
        job_id,
        user.id,
        str(audio_path),
        payload,
        owner_id=user.id,
        project_id=job_id,
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
)
async def get_video(
    video_job_id: str, session: SessionDep, user: CurrentUserDep
) -> VideoStatusResponse:
    job = await job_service.get_owned_video_job(session, video_job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    return VideoStatusResponse(
        video_job_id=job.id,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        # Never expose the durable storage URL here — even to the owner. The only
        # way to fetch a finished video is GET /videos/{id}/download, which
        # re-checks ownership and returns a short-lived presigned URL (or streams
        # locally in dev).
        result_url=None,
        error=job.error,
        theme=(job.payload or {}).get("theme"),
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
)
async def get_video_beats(
    video_job_id: str, session: SessionDep, user: CurrentUserDep
) -> BeatsResponse:
    job = await job_service.get_owned_video_job(session, video_job_id, user.id)
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


# Statuses at which a job is still waiting for its output shape before the clip
# search can run (POST /prepare is accepted only here).
_PREPARABLE = {"queued", "transcribing", "transcribed"}


@app.post(
    "/videos/{video_job_id}/prepare",
    response_model=VideoStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["videos"],
    summary="Supply output choices and start the clip search",
    description=(
        "For a job submitted without a 'format', this records the output shape "
        "(format/aspect, quality, captions) and unblocks the LLM + clip-search "
        "stage. If transcription is still running the choices are stored and the "
        "search starts automatically when beats are ready; if it has finished "
        "(status 'transcribed') the search is enqueued immediately. 409 if the "
        "job has already been prepared or moved past transcription."
    ),
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def prepare_video(
    video_job_id: str,
    body: PrepareRequest,
    session: SessionDep,
    user: CurrentUserDep,
) -> VideoStatusResponse:
    from .formats import resolve_format

    job = await job_service.get_owned_video_job(session, video_job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    if job.status not in _PREPARABLE:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job is '{job.status}'; output choices can only be set before the "
                f"clip search (one of {sorted(_PREPARABLE)})."
            ),
        )
    if (job.payload or {}).get("prepared"):
        raise HTTPException(status_code=409, detail="Job has already been prepared.")

    try:
        fmt = resolve_format(body.format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    quality_tier = (body.quality or DEFAULT_QUALITY).lower()
    if quality_tier not in ALLOWED_QUALITY:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid quality '{body.quality}'. Use one of: {sorted(ALLOWED_QUALITY)}.",
        )

    # Resolve the content theme (default: match the script). A vibe must name a
    # known slug, else the clip search would have nothing to search for.
    theme = {"mode": "script", "vibe": None}
    if body.theme is not None:
        if body.theme.mode == "vibe":
            if not vibes.is_vibe(body.theme.vibe):
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown vibe '{body.theme.vibe}'.",
                )
            theme = {"mode": "vibe", "vibe": body.theme.vibe}
        else:
            theme = {"mode": "script", "vibe": None}

    payload = dict(job.payload or {})
    payload["format"] = {
        "name": fmt.name,
        "orientation": fmt.orientation,
        "width": fmt.width,
        "height": fmt.height,
    }
    payload["quality"] = quality_tier
    payload["subtitles"] = bool(body.subtitles)
    payload["theme"] = theme
    payload["prepared"] = True
    await job_service.update_payload(session, video_job_id, payload)

    # If transcription already finished, kick off the clip search now; otherwise
    # the transcribe worker will enqueue it when beats are ready (it re-reads the
    # prepared flag on completion).
    if job.status == "transcribed":
        await job_queue.llm_queue.enqueue(video_job_id)

    return VideoStatusResponse(
        video_job_id=video_job_id,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        result_url=None,
        error=None,
    )


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
    responses={
        402: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def render_video(
    video_job_id: str,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    body: RenderRequest | None = None,
) -> VideoStatusResponse:
    await enforce_rate_limit(
        settings,
        bucket="render",
        identity=user.id,
        limit=settings.rate_limit_render_per_min,
    )
    job = await job_service.get_owned_video_job(session, video_job_id, user.id)
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
    # Persist the editor's clip swaps (if any) onto the stored assignments before
    # enqueueing, so the worker — which rebuilds the timeline from the DB — uses
    # the user's picks. Batched into the render call (one write) instead of a
    # chatty per-click endpoint. See docs/IMPROVEMENTS.md.
    if body and body.overrides:
        changed = await job_service.apply_candidate_overrides(
            session, video_job_id, body.overrides
        )
        logger.info("render %s: applied %s candidate override(s)", video_job_id, changed)

    # Final output shape can also change at render time (e.g. the user switched
    # aspect/captions on the Pick Clips screen after clip search ran). Fold those
    # into the stored payload that stage_render reads. The fetched stock media's
    # orientation was fixed at clip-search time, so this only changes the encoded
    # output dimensions (renderer cover-scales/crops), not which clips were used.
    if body and (body.format is not None or body.subtitles is not None):
        from .formats import resolve_format

        payload = dict(job.payload or {})
        if body.format is not None:
            try:
                fmt = resolve_format(body.format)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            payload["format"] = {
                "name": fmt.name,
                "orientation": fmt.orientation,
                "width": fmt.width,
                "height": fmt.height,
            }
        if body.subtitles is not None:
            payload["subtitles"] = bool(body.subtitles)
        await job_service.update_payload(session, video_job_id, payload)
        logger.info(
            "render %s: output overrides format=%s subtitles=%s",
            video_job_id,
            body.format,
            body.subtitles,
        )

    # --- Tier limits + credit cost (enforced BEFORE the job starts) ----------
    original_status = job.status
    duration_s = await job_service.get_job_duration_seconds(session, video_job_id)
    me = await user_service.get_user(session, user.id)
    tier = me.tier if me else tiers.DEFAULT_TIER

    violation = tiers.check_video_length(tier, duration_s)
    if violation is not None:
        raise HTTPException(status_code=400, detail=violation.message)

    cost = tiers.credit_cost_for_seconds(duration_s)
    # Friendly pre-check so an under-funded caller is rejected before we move the
    # job (the authoritative, atomic deduction happens only for the race winner).
    if me is not None and me.credits < cost:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient credits: this {duration_s:.0f}s video costs {cost} "
                f"credit(s) but you have {me.credits}. Upgrade or top up to render."
            ),
        )

    # Atomically flip a renderable job to render_queued; only the request that
    # wins the transition enqueues. Racing/duplicate POSTs (e.g. an impatient
    # double click, or a retry after a flaky response) can't enqueue the same job
    # twice, and the worker's guarded claim dedups any leftover queue entries.
    queued = await job_service.try_advance(
        session,
        video_job_id,
        from_statuses=tuple(_RENDERABLE),
        to_status="render_queued",
        progress="render_queued",
    )
    if queued and cost > 0:
        # Only the race winner charges, so duplicate clicks never double-spend.
        # Deduction is atomic (row lock + ledger row in one transaction); the
        # worker refunds this exact amount if the render later fails.
        try:
            await credit_service.spend_credits(
                session, user.id, cost, reason="render", project_id=video_job_id
            )
        except credit_service.InsufficientCreditsError as exc:
            # Balance dropped between the pre-check and the deduction (another
            # render won a concurrent race). Undo the transition and reject.
            await job_service.advance(
                session, video_job_id, original_status, progress=original_status
            )
            raise HTTPException(status_code=402, detail=str(exc)) from exc
        # Re-read so we merge onto any payload the override/format block just wrote.
        fresh = await job_service.get_video_job(session, video_job_id)
        merged = dict((fresh.payload if fresh else job.payload) or {})
        merged["credits_charged"] = cost
        merged["charge_user_id"] = user.id
        merged["project_id"] = video_job_id
        merged["refunded"] = False
        await job_service.update_payload(session, video_job_id, merged)
    if not queued:
        # Lost the race: another request already moved this job out of the
        # renderable set (typically to render_queued/rendering). Treat that as
        # success and report the current state rather than enqueueing again.
        fresh = await job_service.get_video_job(session, video_job_id)
        current = fresh.status if fresh else "render_queued"
        if current not in ("render_queued", "rendering"):
            raise HTTPException(
                status_code=409,
                detail=f"Job is '{current}'; it can no longer be rendered.",
            )
        return VideoStatusResponse(
            video_job_id=video_job_id,
            status=current,  # type: ignore[arg-type]
            progress=(fresh.progress if fresh else "render_queued"),
            result_url=None,
            error=None,
        )

    await job_queue.render_queue.enqueue(video_job_id)
    return VideoStatusResponse(
        video_job_id=video_job_id,
        status="render_queued",  # type: ignore[arg-type]
        progress="render_queued",
        result_url=None,
        error=None,
    )


@app.get(
    "/videos/{video_job_id}/audio",
    tags=["videos"],
    summary="Stream the uploaded narration audio",
    description=(
        "Returns the original narration audio for browser-side preview. In cloud "
        "storage mode, the file is restored from B2 if the local /tmp copy is gone."
    ),
    responses={404: {"model": ErrorResponse}},
)
async def download_audio(
    video_job_id: str, session: SessionDep, settings: SettingsDep, user: CurrentUserDep
):
    job = await job_service.get_owned_video_job(session, video_job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video_job_id.")
    if not job.audio_path:
        raise HTTPException(status_code=404, detail="Audio is not available for this job.")

    try:
        audio_path = await storage.ensure_local_audio(
            settings,
            job.audio_path,
            (job.payload or {}).get("audio_object"),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type = mimetypes.guess_type(audio_path)[0] or "audio/mpeg"
    return FileResponse(
        audio_path,
        media_type=media_type,
        filename=f"{video_job_id}{Path(audio_path).suffix or '.audio'}",
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
)
async def download_video(
    video_job_id: str, session: SessionDep, settings: SettingsDep, user: CurrentUserDep
):
    # Ownership is verified before any URL is produced: a finished video link is
    # only ever returned to its owner, and the cloud URL is a short-lived signed
    # token (see storage.b2_download_url) — never a public guessable path.
    job = await job_service.get_owned_video_job(session, video_job_id, user.id)
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


def _tier_info(tier: str) -> TierInfo:
    cfg = tiers.get_tier_config(tier)
    return TierInfo(
        name=cfg.name,
        label=cfg.label,
        monthly_credits=cfg.monthly_credits,
        max_video_seconds=cfg.max_video_seconds,
        max_resolution_height=cfg.max_resolution_height,
        watermark=cfg.watermark,
        features=list(cfg.features),
    )


@app.get(
    "/me",
    response_model=MeResponse,
    tags=["account"],
    summary="Get the authenticated user's account (tier + credit balance)",
)
async def get_me(session: SessionDep, user: CurrentUserDep) -> MeResponse:
    me = await user_service.get_user(session, user.id)
    if me is None:
        # get_current_user upserts the user, so this is defensive only.
        raise HTTPException(status_code=404, detail="User not found.")
    return MeResponse(
        id=me.id,
        email=me.email,
        name=me.name,
        tier=me.tier,
        credits=me.credits,
        tier_info=_tier_info(me.tier),
    )


@app.get(
    "/me/credits",
    response_model=CreditsResponse,
    tags=["account"],
    summary="Get the authenticated user's credit balance and ledger",
)
async def get_my_credits(session: SessionDep, user: CurrentUserDep) -> CreditsResponse:
    me = await user_service.get_user(session, user.id)
    txns = await credit_service.list_transactions(session, user.id)
    return CreditsResponse(
        credits=me.credits if me else 0,
        transactions=[
            CreditTransactionOut(
                id=t.id,
                delta=t.delta,
                reason=t.reason,
                project_id=t.project_id,
                created_at=t.created_at.isoformat() if t.created_at else "",
            )
            for t in txns
        ],
    )


def _project_out(
    project, progress: str | None = None, error: str | None = None
) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        input_type=project.input_type,
        status=project.status,
        progress=progress,
        error=error,
        # Same rule as GET /videos/{id}: no raw storage URL in list/detail.
        result_url=None,
        created_at=project.created_at.isoformat() if project.created_at else "",
        updated_at=project.updated_at.isoformat() if project.updated_at else "",
    )


@app.get(
    "/projects",
    response_model=ProjectsResponse,
    tags=["projects"],
    summary="List the authenticated user's projects",
)
async def list_projects(session: SessionDep, user: CurrentUserDep) -> ProjectsResponse:
    projects = await project_service.list_projects(session, user.id)
    # One batched lookup of the underlying jobs' stage/error so the UI can show
    # *where* each processing project is (and why a failed one failed).
    progress_map = await job_service.get_progress_map(session, [p.id for p in projects])
    return ProjectsResponse(
        projects=[
            _project_out(p, *progress_map.get(p.id, (None, None))) for p in projects
        ]
    )


@app.get(
    "/projects/{project_id}",
    response_model=ProjectOut,
    tags=["projects"],
    summary="Get one of the authenticated user's projects",
    description="Returns 404 (not 403) if the project isn't the caller's.",
    responses={404: {"model": ErrorResponse}},
)
async def get_project(
    project_id: str, session: SessionDep, user: CurrentUserDep
) -> ProjectOut:
    project = await project_service.get_project(session, project_id, user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Unknown project.")
    progress_map = await job_service.get_progress_map(session, [project.id])
    return _project_out(project, *progress_map.get(project.id, (None, None)))


@app.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["projects"],
    summary="Delete one of the authenticated user's projects",
    description=(
        "Removes the project, its underlying job/beats, and its stored media "
        "(rendered result + narration). Returns 404 (not 403) if the project "
        "isn't the caller's. Frees a project slot against the tier cap."
    ),
    responses={404: {"model": ErrorResponse}},
)
async def delete_project(
    project_id: str,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
) -> Response:
    project = await project_service.get_project(session, project_id, user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Unknown project.")

    # The job id mirrors the project id (1:1). Grab the durable audio object
    # name before deleting the row so we can clean it out of B2 too.
    job = await job_service.get_video_job(session, project_id)
    audio_object = (job.payload or {}).get("audio_object") if job is not None else None

    await job_service.delete_job_cascade(session, project_id)
    await project_service.delete_project(session, project_id, user.id)
    # Storage cleanup is best-effort and never blocks the delete.
    await storage.delete_stored_objects(settings, project_id, audio_object)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness probe")
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)
