"""HTTP implementation of :class:`ClipClient`."""

from __future__ import annotations

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

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}"}

    async def submit(
        self,
        job_id: str,
        items: list[dict[str, Any]],
        credentials: dict[str, str | None],
        sources: list[str] | None,
        *,
        orientation: str | None = None,
        quality: str | None = None,
        rank: bool = True,
        per_page: int | None = None,
    ) -> None:
        # Source API keys (Pexels/Pixabay/Flickr) are intentionally NOT sent in
        # the request: the clip-server reads them from its own environment. We
        # keep accepting ``credentials`` on the interface for back-compat, but
        # drop them here so keys never travel over the wire.
        del credentials
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
            credentials=ClipJobCredentials(),
            # orientation is forwarded to Pexels so fetched media already matches
            # the target aspect ratio (landscape | portrait | square); quality
            # selects the downloaded resolution tier (sd | hd | max). rank=False
            # (vibe mode) skips CLIP ranking server-side.
            options=ClipJobOptions(
                min_score=0.15,
                orientation=orientation,
                quality=quality,
                rank=rank,
                per_page=per_page,
            ),
        )
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
            create = await client.post("/jobs", json=body.model_dump(), headers=self._headers)
            create.raise_for_status()

    async def poll(self, job_id: str) -> ClipJobStatusResponse:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
            poll = await client.get(f"/jobs/{job_id}", headers=self._headers)
            poll.raise_for_status()
            return ClipJobStatusResponse.model_validate(poll.json())
