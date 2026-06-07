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
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Settings

if TYPE_CHECKING:
    from b2sdk.v2 import Bucket

logger = logging.getLogger(__name__)


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
    bucket.upload_local_file(local_file=str(local_path), file_name=remote_name)
    if settings.b2_public_base_url:
        return f"{settings.b2_public_base_url.rstrip('/')}/{remote_name}"
    return bucket.get_download_url(remote_name)


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
    await asyncio.to_thread(_upload_audio_b2_sync, settings, remote_name, Path(local_path))
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
        await asyncio.to_thread(
            _download_b2_object_sync, settings, audio_object, Path(audio_path)
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
    return await asyncio.to_thread(_b2_download_url_sync, settings, job_id, valid_s)


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

    url = await asyncio.to_thread(_upload_to_b2_sync, settings, remote_name, Path(local_path))
    logger.info("uploaded job %s to B2 (%s) -> %s", job_id, remote_name, url)

    try:
        Path(local_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove local file after B2 upload: %s", local_path)

    return url
