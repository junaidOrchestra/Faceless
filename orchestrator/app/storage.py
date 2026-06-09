"""Result storage backends: local disk or Backblaze B2 cloud.

The rendered mp4 is always written to local disk first (FFmpeg needs a real
file). :func:`publish_result` then decides where it lives long-term:

* ``storage_local=True``  -> leave it on disk, return a local ``result_url``.
* ``storage_local=False`` -> upload to Backblaze B2, return its download URL,
  and remove the local copy.

``b2sdk`` is imported lazily and authorized once per process, so a purely-local
deployment never needs the dependency configured.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Settings

if TYPE_CHECKING:
    from b2sdk.v2 import Bucket

logger = logging.getLogger(__name__)


async def _b2_call(settings: Settings, func, *args):
    """Run a blocking B2 op off the loop with a wall-clock backstop.

    b2sdk retries internally and can stall for minutes on an outage. wait_for
    can't kill the worker thread (it keeps running until the SDK gives up), but
    it stops the caller from blocking forever so submit/render/download fail
    predictably instead of hanging a worker or request.
    """

    return await asyncio.wait_for(
        asyncio.to_thread(func, *args), timeout=settings.b2_timeout_s
    )


@lru_cache
def _get_b2_bucket(key_id: str, application_key: str, bucket_name: str) -> "Bucket":
    """Authorize against B2 once and return the target bucket (cached per creds)."""

    from b2sdk.v2 import B2Api, InMemoryAccountInfo

    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", key_id, application_key)
    return api.get_bucket_by_name(bucket_name)


def _upload_to_b2_sync(settings: Settings, remote_name: str, local_path: Path) -> str:
    """Blocking B2 upload; returns the file's download URL. Run via ``to_thread``."""

    bucket = _get_b2_bucket(
        settings.b2_key_id,  # type: ignore[arg-type]
        settings.b2_application_key,  # type: ignore[arg-type]
        settings.b2_bucket_name,  # type: ignore[arg-type]
    )
    _delete_b2_versions_sync(bucket, remote_name)
    bucket.upload_local_file(local_file=str(local_path), file_name=remote_name)
    if settings.b2_public_base_url:
        return f"{settings.b2_public_base_url.rstrip('/')}/{remote_name}"
    return bucket.get_download_url(remote_name)


def _delete_b2_versions_sync(bucket: "Bucket", remote_name: str) -> None:
    """Remove existing versions for a result object before uploading its replacement.

    B2 is versioned storage: uploading ``same/name.mp4`` again creates another
    version with the same file name instead of replacing the previous version.
    The app uses deterministic result names (``{job_id}.mp4``), so a rerender of
    the same job would otherwise appear as duplicate files in the B2 console.
    Cleanup is best-effort so a bucket key without delete permission can still
    upload the new render; the old versions will just remain visible in B2.
    """

    deleted = 0
    try:
        for version in list(bucket.list_file_versions(remote_name)):
            if version.file_name != remote_name:
                continue
            bucket.delete_file_version(version.id_, version.file_name)
            deleted += 1
    except Exception as exc:  # noqa: BLE001 - do not fail rendering if cleanup is denied
        logger.warning(
            "could not delete old B2 versions for %s before upload: %s",
            remote_name,
            exc,
        )
        return
    if deleted:
        logger.info("deleted %s old B2 version(s) for %s before upload", deleted, remote_name)


def local_result_path(settings: Settings, job_id: str) -> Path:
    """Filesystem path where the renderer wrote the final mp4 (local-mode download)."""

    return Path(settings.render_temp_dir) / f"{job_id}.mp4"


def _audio_remote_name(settings: Settings, job_id: str, suffix: str) -> str:
    prefix = settings.b2_prefix.strip("/")
    name = f"audio/{job_id}{suffix or '.bin'}"
    return f"{prefix}/{name}" if prefix else name


def _upload_audio_b2_sync(settings: Settings, remote_name: str, local_path: Path) -> None:
    bucket = _get_b2_bucket(
        settings.b2_key_id,  # type: ignore[arg-type]
        settings.b2_application_key,  # type: ignore[arg-type]
        settings.b2_bucket_name,  # type: ignore[arg-type]
    )
    bucket.upload_local_file(local_file=str(local_path), file_name=remote_name)


def _download_b2_object_sync(settings: Settings, remote_name: str, local_path: Path) -> None:
    bucket = _get_b2_bucket(
        settings.b2_key_id,  # type: ignore[arg-type]
        settings.b2_application_key,  # type: ignore[arg-type]
        settings.b2_bucket_name,  # type: ignore[arg-type]
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    bucket.download_file_by_name(remote_name).save_to(str(local_path))


async def publish_audio(settings: Settings, job_id: str, local_path: str) -> str | None:
    """Persist the narration audio to durable storage; return its B2 object name.

    The render stage runs on demand (possibly after a restart or on another
    replica), but the uploaded audio lives in ephemeral ``/tmp``. In B2 mode we
    therefore copy it to the bucket at submit so it can be re-fetched later.
    Returns ``None`` in local mode (or if B2 isn't configured), where the
    on-disk copy is the source of truth.
    """

    if settings.storage_local:
        return None
    if not (settings.b2_key_id and settings.b2_application_key and settings.b2_bucket_name):
        return None

    remote_name = _audio_remote_name(settings, job_id, Path(local_path).suffix)
    await _b2_call(settings, _upload_audio_b2_sync, settings, remote_name, Path(local_path))
    logger.info("persisted narration for job %s to B2 (%s)", job_id, remote_name)
    return remote_name


async def ensure_local_audio(
    settings: Settings, audio_path: str, audio_object: str | None
) -> str:
    """Return a local path to the narration, re-downloading from B2 if ``/tmp`` lost it.

    Used by the render/transcribe stages so an ephemeral-storage restart between
    submit and render doesn't strand the job with a missing audio file.
    """

    if Path(audio_path).exists():
        return audio_path
    if audio_object and not settings.storage_local:
        logger.info("local narration missing (%s); re-fetching %s from B2", audio_path, audio_object)
        await _b2_call(
            settings, _download_b2_object_sync, settings, audio_object, Path(audio_path)
        )
        return audio_path
    raise FileNotFoundError(
        f"Narration audio is unavailable at {audio_path} and no durable copy "
        "exists to recover it (set STORAGE_LOCAL=false with B2 configured so "
        "audio survives restarts)."
    )


def _b2_download_url_sync(settings: Settings, job_id: str, valid_s: int) -> str:
    prefix = settings.b2_prefix.strip("/")
    remote_name = f"{prefix}/{job_id}.mp4" if prefix else f"{job_id}.mp4"

    # A configured public base URL implies the bucket/CDN is publicly readable.
    if settings.b2_public_base_url:
        return f"{settings.b2_public_base_url.rstrip('/')}/{remote_name}"

    bucket = _get_b2_bucket(
        settings.b2_key_id,  # type: ignore[arg-type]
        settings.b2_application_key,  # type: ignore[arg-type]
        settings.b2_bucket_name,  # type: ignore[arg-type]
    )
    download_url = bucket.get_download_url(remote_name)
    # Presign so private buckets are downloadable via a time-limited token.
    token = bucket.get_download_authorization(
        file_name_prefix=remote_name, valid_duration_in_seconds=valid_s
    )
    return f"{download_url}?Authorization={token}"


async def b2_download_url(settings: Settings, job_id: str, *, valid_s: int = 3600) -> str:
    """Return a downloadable B2 URL (presigned for private buckets) off the loop."""

    if not (settings.b2_key_id and settings.b2_application_key and settings.b2_bucket_name):
        raise RuntimeError("Backblaze B2 is not configured.")
    return await _b2_call(settings, _b2_download_url_sync, settings, job_id, valid_s)


def _b2_object_url_sync(settings: Settings, remote_name: str, valid_s: int) -> str:
    """Downloadable URL for an arbitrary B2 object (public base URL or presigned)."""

    if settings.b2_public_base_url:
        return f"{settings.b2_public_base_url.rstrip('/')}/{remote_name}"

    bucket = _get_b2_bucket(
        settings.b2_key_id,  # type: ignore[arg-type]
        settings.b2_application_key,  # type: ignore[arg-type]
        settings.b2_bucket_name,  # type: ignore[arg-type]
    )
    download_url = bucket.get_download_url(remote_name)
    token = bucket.get_download_authorization(
        file_name_prefix=remote_name, valid_duration_in_seconds=valid_s
    )
    return f"{download_url}?Authorization={token}"


async def object_download_url(
    settings: Settings, remote_name: str, *, valid_s: int = 604800
) -> str:
    """Return a downloadable URL for a stored object (e.g. an uploaded source video).

    Used to hand the renderer (and the editor's clip picker) a fetchable URL for
    the user's own uploaded/recorded video, which is persisted alongside the
    narration in B2. Presigned tokens default to a long validity (7 days) so a
    render queued well after submit can still fetch the footage.
    """

    if not (settings.b2_key_id and settings.b2_application_key and settings.b2_bucket_name):
        raise RuntimeError("Backblaze B2 is not configured.")
    return await _b2_call(settings, _b2_object_url_sync, settings, remote_name, valid_s)


def _delete_b2_object_sync(settings: Settings, remote_name: str) -> None:
    """Delete every version of a single B2 object (best-effort)."""

    bucket = _get_b2_bucket(
        settings.b2_key_id,  # type: ignore[arg-type]
        settings.b2_application_key,  # type: ignore[arg-type]
        settings.b2_bucket_name,  # type: ignore[arg-type]
    )
    _delete_b2_versions_sync(bucket, remote_name)


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
    if not (settings.b2_key_id and settings.b2_application_key and settings.b2_bucket_name):
        return

    prefix = settings.b2_prefix.strip("/")
    result_name = f"{prefix}/{job_id}.mp4" if prefix else f"{job_id}.mp4"
    remote_names = [result_name]
    if audio_object:
        remote_names.append(audio_object)
    for remote_name in remote_names:
        try:
            await _b2_call(settings, _delete_b2_object_sync, settings, remote_name)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            logger.warning("could not delete B2 object %s for job %s", remote_name, job_id)


async def publish_result(settings: Settings, job_id: str, local_path: str) -> str:
    """Return the final ``result_url`` for a freshly rendered video.

    Local mode returns a URL under ``result_base_url``. B2 mode uploads the file
    (off the event loop) and returns its download URL, then deletes the local
    copy so the mounted output dir doesn't accumulate cloud-stored videos.
    """

    if settings.storage_local:
        return f"{settings.result_base_url.rstrip('/')}/{job_id}.mp4"

    if not (settings.b2_key_id and settings.b2_application_key and settings.b2_bucket_name):
        raise RuntimeError(
            "storage_local is false but Backblaze B2 is not fully configured "
            "(need B2_KEY_ID, B2_APPLICATION_KEY, B2_BUCKET_NAME)."
        )

    prefix = settings.b2_prefix.strip("/")
    remote_name = f"{prefix}/{job_id}.mp4" if prefix else f"{job_id}.mp4"

    url = await _b2_call(settings, _upload_to_b2_sync, settings, remote_name, Path(local_path))
    logger.info("uploaded job %s to B2 (%s) -> %s", job_id, remote_name, url)

    try:
        Path(local_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove local file after B2 upload: %s", local_path)

    return url
