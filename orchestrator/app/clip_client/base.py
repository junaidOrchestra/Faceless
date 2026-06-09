"""CLIP server HTTP client abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .schemas import ClipJobStatusResponse


class ClipClient(ABC):
    @abstractmethod
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
        """Submit a batch job (fire-and-forget). Idempotent on ``job_id``.

        ``rank=False`` (vibe mode) tells the server to skip CLIP ranking and return
        raw source results; ``per_page`` overrides results-per-source-query.
        """

    @abstractmethod
    async def poll(self, job_id: str) -> ClipJobStatusResponse:
        """Fetch the current status/results of a previously submitted job."""
