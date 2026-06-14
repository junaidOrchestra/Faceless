"""Result storage backends: local disk or S3-compatible object storage (R2).

The rendered mp4 is always written to local disk first (FFmpeg needs a real
file). :func:`publish_result` then decides where it lives long-term:

* ``storage_local=True``  -> leave it on disk, return a local ``result_url``.
* ``storage_local=False`` -> upload to the S3-compatible bucket (Cloudflare R2),
  return a download URL, and remove the local copy.

All cloud operations go through the boto3 S3 client in :mod:`app.s3_storage`,
so the same client/credentials power both the result store and the multipart
upload flow. The client is created lazily, so a purely-local deployment never
needs the dependency configured.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from . import s3_storage
from .config import Settings

logger = logging.getLogger(__name__)

# R2 (and S3) cap presigned URL lifetimes at 7 days.
_MAX_PRESIGN_S = 7 * 24 * 3600


def _s3_configured(settings: Settings) -> bool:
    """True when enough S3/R2 settings are present to talk to the bucket."""

    return bool(
        settings.s3_access_key_id
        and settings.s3_secret_access_key
        and settings.s3_bucket
        and settings.s3_endpoint_url
    )


def cloud_enabled(settings: Settings) -> bool:
    """True when cloud storage is the active backend (not local) and configured.

    Direct browser->bucket multipart uploads only work in this mode; local mode
    has no presignable endpoint.
    """

    return not settings.storage_local and _s3_configured(settings)


def source_object_prefix(settings: Settings, job_id: str) -> str:
    """Key prefix every uploaded source object for ``job_id`` must live under.

    Used to verify a client-supplied object_key at finalize belongs to the job
    it claims (a client can't complete a multipart upload onto an arbitrary key).
    """

    prefix = settings.s3_prefix.strip("/")
    base = f"audio/{job_id}"
    return f"{prefix}/{base}" if prefix else base


def local_result_path(settings: Settings, job_id: str) -> Path:
    """Filesystem path where the renderer wrote the final mp4 (local-mode download)."""

    return Path(settings.render_temp_dir) / f"{job_id}.mp4"


def _result_remote_name(settings: Settings, job_id: str) -> str:
    prefix = settings.s3_prefix.strip("/")
    name = f"{job_id}.mp4"
    return f"{prefix}/{name}" if prefix else name


def _audio_remote_name(settings: Settings, job_id: str, suffix: str) -> str:
    prefix = settings.s3_prefix.strip("/")
    name = f"audio/{job_id}{suffix or '.bin'}"
    return f"{prefix}/{name}" if prefix else name


def _beat_clip_remote_name(settings: Settings, job_id: str, slot: object, suffix: str) -> str:
    prefix = settings.s3_prefix.strip("/")
    name = f"beats/{job_id}/{slot}{suffix or '.webm'}"
    return f"{prefix}/{name}" if prefix else name


def _public_url(settings: Settings, remote_name: str) -> str | None:
    """Permanent URL for a public bucket / CDN, or None when not configured."""

    if settings.s3_public_base_url:
        return f"{settings.s3_public_base_url.rstrip('/')}/{remote_name}"
    return None


async def publish_result(settings: Settings, job_id: str, local_path: str) -> str:
    """Return the final ``result_url`` for a freshly rendered video.

    Local mode returns a URL under ``result_base_url``. Cloud mode uploads the
    file (off the event loop) and returns a download URL, then deletes the local
    copy so the mounted output dir doesn't accumulate cloud-stored videos.
    """

    if settings.storage_local:
        return f"{settings.result_base_url.rstrip('/')}/{job_id}.mp4"

    if not _s3_configured(settings):
        raise RuntimeError(
            "storage_local is false but S3/R2 storage is not fully configured "
            "(need S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET)."
        )

    remote_name = _result_remote_name(settings, job_id)
    await s3_storage.upload_file(settings, remote_name, Path(local_path), "video/mp4")
    url = _public_url(settings, remote_name) or await s3_storage.presign_get_url(
        settings, remote_name, expires_s=3600
    )
    logger.info("uploaded job %s to R2 (%s)", job_id, remote_name)

    try:
        Path(local_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove local file after upload: %s", local_path)

    return url


async def publish_audio(settings: Settings, job_id: str, local_path: str) -> str | None:
    """Persist the narration audio to durable storage; return its object key.

    The render stage runs on demand (possibly after a restart or on another
    replica), but the uploaded audio lives in ephemeral ``/tmp``. In cloud mode
    we therefore copy it to the bucket at submit so it can be re-fetched later.
    Returns ``None`` in local mode (or if R2 isn't configured), where the
    on-disk copy is the source of truth.
    """

    if settings.storage_local:
        return None
    if not _s3_configured(settings):
        return None

    remote_name = _audio_remote_name(settings, job_id, Path(local_path).suffix)
    await s3_storage.upload_file(settings, remote_name, Path(local_path))
    logger.info("persisted narration for job %s to R2 (%s)", job_id, remote_name)
    return remote_name


async def publish_beat_clip(
    settings: Settings, job_id: str, slot: object, local_path: str
) -> str:
    """Persist a per-beat recorded clip and return a fetchable URL for the renderer.

    ``slot`` is just the storage key segment (a beat index for per-beat overrides,
    or a unique token for inserted cards so two inserts never collide).

    Local mode: keep it on disk and return the absolute path (the renderer reads
    non-http paths straight from disk). Cloud mode: upload it and return a
    long-lived download URL (presigned for private buckets), mirroring how a
    user's uploaded source video is handled.
    """

    if settings.storage_local:
        return str(local_path)
    if not _s3_configured(settings):
        # No durable store configured — fall back to the local path so a purely
        # local dev box still works even with storage_local mistakenly false.
        return str(local_path)

    suffix = Path(local_path).suffix or ".webm"
    remote_name = _beat_clip_remote_name(settings, job_id, slot, suffix)
    await s3_storage.upload_file(settings, remote_name, Path(local_path))
    logger.info("persisted beat clip %s for job %s to R2 (%s)", slot, job_id, remote_name)
    return await object_download_url(settings, remote_name)


async def ensure_local_audio(
    settings: Settings, audio_path: str, audio_object: str | None
) -> str:
    """Return a local path to the narration, re-downloading from R2 if ``/tmp`` lost it.

    Used by the render/transcribe stages so an ephemeral-storage restart between
    submit and render doesn't strand the job with a missing audio file.
    """

    if Path(audio_path).exists():
        return audio_path
    if audio_object and not settings.storage_local:
        logger.info(
            "local narration missing (%s); re-fetching %s from R2", audio_path, audio_object
        )
        await s3_storage.download_file(settings, audio_object, Path(audio_path))
        return audio_path
    raise FileNotFoundError(
        f"Narration audio is unavailable at {audio_path} and no durable copy "
        "exists to recover it (set STORAGE_LOCAL=false with S3/R2 configured so "
        "audio survives restarts)."
    )


async def result_download_url(settings: Settings, job_id: str, *, valid_s: int = 3600) -> str:
    """Return a downloadable URL for a rendered result (presigned for private buckets)."""

    if not _s3_configured(settings):
        raise RuntimeError("S3/R2 storage is not configured.")
    remote_name = _result_remote_name(settings, job_id)
    public = _public_url(settings, remote_name)
    if public:
        return public
    return await s3_storage.presign_get_url(
        settings, remote_name, expires_s=min(valid_s, _MAX_PRESIGN_S)
    )


async def object_download_url(
    settings: Settings, remote_name: str, *, valid_s: int = _MAX_PRESIGN_S
) -> str:
    """Return a downloadable URL for a stored object (e.g. an uploaded source video).

    Used to hand the renderer (and the editor's clip picker) a fetchable URL for
    the user's own uploaded/recorded video, which is persisted alongside the
    narration in R2. Presigned tokens default to the maximum validity (7 days)
    so a render queued well after submit can still fetch the footage.
    """

    if not _s3_configured(settings):
        raise RuntimeError("S3/R2 storage is not configured.")
    public = _public_url(settings, remote_name)
    if public:
        return public
    return await s3_storage.presign_get_url(
        settings, remote_name, expires_s=min(valid_s, _MAX_PRESIGN_S)
    )


async def delete_stored_objects(
    settings: Settings, job_id: str, audio_object: str | None = None
) -> None:
    """Best-effort removal of a job's stored media (rendered result + narration).

    Called when a user deletes a project so freed projects also free storage.
    Never raises: storage cleanup must not block the delete from succeeding, so
    failures are logged and swallowed.
    """

    # Local copies (present in local mode, or as leftovers in cloud mode).
    try:
        local_result_path(settings, job_id).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove local result for job %s", job_id)
    upload_dir = Path(settings.render_temp_dir) / "uploads" / job_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir, ignore_errors=True)

    if settings.storage_local:
        return
    if not _s3_configured(settings):
        return

    remote_names = [_result_remote_name(settings, job_id)]
    if audio_object:
        remote_names.append(audio_object)
    for remote_name in remote_names:
        try:
            await s3_storage.delete_object(settings, remote_name)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            logger.warning("could not delete R2 object %s for job %s", remote_name, job_id)
