"""In-process stub ClipClient for smoke tests."""

from __future__ import annotations

from typing import Any

from .base import ClipClient
from .schemas import ClipJobItemResult, ClipJobStatusResponse, ClipRankedAsset


class StubClipClient(ClipClient):
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
        del job_id, credentials, sources, poll_interval_s, poll_timeout_s
        results: list[ClipJobItemResult] = []
        for it in items:
            results.append(
                ClipJobItemResult(
                    ref=str(it["ref"]),
                    assets=[
                        ClipRankedAsset(
                            platform="stub",
                            kind="photo",
                            media_url="https://example.com/a.jpg",
                            preview_url="stub://preview/x",
                            attribution_name="Stub",
                            attribution_url="https://example.com",
                            license="CC0",
                            score=0.9,
                        )
                    ],
                )
            )
        return ClipJobStatusResponse(job_id="stub", status="done", items=results)
