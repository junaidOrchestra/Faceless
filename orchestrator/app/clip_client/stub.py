"""In-process stub ClipClient for smoke tests.

``submit`` records the requested items in memory keyed by job id; ``poll`` then
returns an immediately-``done`` response with one canned asset per ref. This
mirrors the real submit/poll split used by the staged pipeline.
"""

from __future__ import annotations

from typing import Any

from .base import ClipClient
from .schemas import ClipJobItemResult, ClipJobStatusResponse, ClipRankedAsset


class StubClipClient(ClipClient):
    def __init__(self) -> None:
        self._jobs: dict[str, list[dict[str, Any]]] = {}

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
        del credentials, sources, orientation, quality, rank, per_page
        self._jobs[job_id] = list(items)

    async def poll(self, job_id: str) -> ClipJobStatusResponse:
        items = self._jobs.get(job_id, [])
        results: list[ClipJobItemResult] = []
        for it in items:
            ref = str(it["ref"])
            results.append(
                ClipJobItemResult(
                    ref=ref,
                    assets=[
                        ClipRankedAsset(
                            platform="stub",
                            kind="photo",
                            media_url=f"https://example.com/{ref}.jpg",
                            preview_url="stub://preview/x",
                            attribution_name="Stub",
                            attribution_url="https://example.com",
                            license="CC0",
                            score=0.9,
                        )
                    ],
                )
            )
        return ClipJobStatusResponse(job_id=job_id, status="done", items=results)
