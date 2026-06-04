"""HTTP implementation of :class:`ClipClient`."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import ClipClient
from .schemas import (
    ClipCreateJobRequest,
    ClipJobCredentials,
    ClipJobItemInput,
    ClipJobOptions,
    ClipJobStatusResponse,
)

logger = logging.getLogger(__name__)


class HttpClipClient(ClipClient):
    def __init__(self, base_url: str, secret: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret

    async def submit_and_poll(
        self,
        job_id: str,
        items: list[dict[str, Any]],
        credentials: dict[str, str | None],
        sources: list[str] | None,
        *,
        poll_interval_s: float,
        poll_timeout_s: float,
    ) -> ClipJobStatusResponse:
        headers = {"Authorization": f"Bearer {self._secret}"}
        body = ClipCreateJobRequest(
            job_id=job_id,
            items=[
                ClipJobItemInput(
                    ref=str(it["ref"]),
                    keyword=str(it["keyword"]),
                    sources=it.get("sources") or sources,
                )
                for it in items
            ],
            credentials=ClipJobCredentials(pexels=credentials.get("pexels")),
            options=ClipJobOptions(min_score=0.15),
        )
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
            create = await client.post("/jobs", json=body.model_dump(), headers=headers)
            create.raise_for_status()

            elapsed = 0.0
            while elapsed < poll_timeout_s:
                poll = await client.get(f"/jobs/{job_id}", headers=headers)
                poll.raise_for_status()
                status = ClipJobStatusResponse.model_validate(poll.json())
                if status.status in ("done", "failed"):
                    return status
                await asyncio.sleep(poll_interval_s)
                elapsed += poll_interval_s
        raise TimeoutError(f"CLIP job {job_id} timed out after {poll_timeout_s}s")
