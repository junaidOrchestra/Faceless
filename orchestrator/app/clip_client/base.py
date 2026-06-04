"""CLIP server HTTP client abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .schemas import ClipJobStatusResponse


class ClipClient(ABC):
    @abstractmethod
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
        """Submit a batch job and poll until terminal status."""
