"""S3-compatible object storage helpers (R2, B2 S3, MinIO, ...)."""

from __future__ import annotations

import asyncio
import logging
import math
import mimetypes
from pathlib import Path
from functools import lru_cache
from typing import Any

from .config import Settings

logger = logging.getLogger(__name__)


def multipart_upload_enabled(settings: Settings) -> bool:
    return bool(
        settings.s3_access_key_id
        and settings.s3_secret_access_key
        and settings.s3_bucket
        and settings.s3_endpoint_url
    )


@lru_cache
def _s3_client(key_id: str, secret: str, endpoint: str, region: str):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            # Fail fast on a misconfigured/unreachable endpoint instead of letting
            # boto3's default long timeouts + retries hang the request ~18s. A
            # bad endpoint/credentials should surface as a quick, clear error.
            connect_timeout=5,
            read_timeout=15,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def _client(settings: Settings):
    return _s3_client(
        settings.s3_access_key_id,  # type: ignore[arg-type]
        settings.s3_secret_access_key,  # type: ignore[arg-type]
        settings.s3_endpoint_url,  # type: ignore[arg-type]
        settings.s3_region,
    )


def _create_multipart_sync(
    settings: Settings, object_key: str, content_type: str | None
) -> str:
    client = _client(settings)
    kwargs: dict[str, Any] = {
        "Bucket": settings.s3_bucket,
        "Key": object_key,
    }
    if content_type:
        kwargs["ContentType"] = content_type
    resp = client.create_multipart_upload(**kwargs)
    return str(resp["UploadId"])


def _presign_part_sync(
    settings: Settings, object_key: str, upload_id: str, part_number: int
) -> str:
    client = _client(settings)
    return client.generate_presigned_url(
        "upload_part",
        Params={
            "Bucket": settings.s3_bucket,
            "Key": object_key,
            "UploadId": upload_id,
            "PartNumber": part_number,
        },
        ExpiresIn=3600,
    )


def _complete_multipart_sync(
    settings: Settings,
    object_key: str,
    upload_id: str,
    parts: list[dict[str, Any]],
) -> None:
    client = _client(settings)
    client.complete_multipart_upload(
        Bucket=settings.s3_bucket,
        Key=object_key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def _head_object_sync(settings: Settings, object_key: str) -> int:
    client = _client(settings)
    resp = client.head_object(Bucket=settings.s3_bucket, Key=object_key)
    return int(resp["ContentLength"])


def _upload_file_sync(
    settings: Settings,
    object_key: str,
    local_path: Path,
    content_type: str | None = None,
) -> None:
    client = _client(settings)
    extra_args: dict[str, Any] = {}
    guessed = content_type or mimetypes.guess_type(str(local_path))[0]
    if guessed:
        extra_args["ContentType"] = guessed
    kwargs: dict[str, Any] = {}
    if extra_args:
        kwargs["ExtraArgs"] = extra_args
    client.upload_file(str(local_path), settings.s3_bucket, object_key, **kwargs)


def _download_file_sync(settings: Settings, object_key: str, local_path: Path) -> None:
    client = _client(settings)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(settings.s3_bucket, object_key, str(local_path))


def download_file_sync(settings: Settings, object_key: str, local_path: Path) -> None:
    """Synchronous object download for code already running in a worker thread."""

    _download_file_sync(settings, object_key, local_path)


def _delete_object_sync(settings: Settings, object_key: str) -> None:
    client = _client(settings)
    client.delete_object(Bucket=settings.s3_bucket, Key=object_key)


def _presign_get_sync(settings: Settings, object_key: str, *, expires_s: int) -> str:
    client = _client(settings)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": object_key},
        ExpiresIn=expires_s,
    )


def _presign_put_sync(settings: Settings, object_key: str, *, expires_s: int) -> str:
    client = _client(settings)
    # Content-Type is intentionally left unsigned so the browser can PUT the blob
    # with whatever type it sets without breaking the signature.
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": object_key},
        ExpiresIn=expires_s,
    )


async def create_multipart_upload(
    settings: Settings, object_key: str, content_type: str | None
) -> str:
    return await asyncio.to_thread(
        _create_multipart_sync, settings, object_key, content_type
    )


async def presign_upload_part(
    settings: Settings, object_key: str, upload_id: str, part_number: int
) -> str:
    return await asyncio.to_thread(
        _presign_part_sync, settings, object_key, upload_id, part_number
    )


async def complete_multipart_upload(
    settings: Settings,
    object_key: str,
    upload_id: str,
    parts: list[dict[str, Any]],
) -> None:
    await asyncio.to_thread(
        _complete_multipart_sync, settings, object_key, upload_id, parts
    )


async def head_object_size(settings: Settings, object_key: str) -> int:
    return await asyncio.to_thread(_head_object_sync, settings, object_key)


async def upload_file(
    settings: Settings,
    object_key: str,
    local_path: Path,
    content_type: str | None = None,
) -> None:
    await asyncio.to_thread(
        _upload_file_sync, settings, object_key, local_path, content_type
    )


async def download_file(settings: Settings, object_key: str, local_path: Path) -> None:
    await asyncio.to_thread(_download_file_sync, settings, object_key, local_path)


async def delete_object(settings: Settings, object_key: str) -> None:
    await asyncio.to_thread(_delete_object_sync, settings, object_key)


async def presign_get_url(
    settings: Settings, object_key: str, *, expires_s: int = 3600
) -> str:
    return await asyncio.to_thread(
        _presign_get_sync, settings, object_key, expires_s=expires_s
    )


async def presign_put_url(
    settings: Settings, object_key: str, *, expires_s: int = 3600
) -> str:
    """Presigned single-PUT URL (browser -> bucket) for a whole small object."""

    return await asyncio.to_thread(
        _presign_put_sync, settings, object_key, expires_s=expires_s
    )


def plan_multipart_parts(size_bytes: int, part_size: int) -> tuple[int, int]:
    """Return (part_size_bytes, part_count) for a declared upload size."""

    part_size = max(5 * 1024 * 1024, int(part_size))
    part_count = max(1, math.ceil(size_bytes / part_size))
    return part_size, part_count
