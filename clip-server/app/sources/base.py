"""Stock source abstraction and the neutral :class:`Candidate` record."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

MediaKind = Literal["photo", "video"]


@dataclass(slots=True)
class Candidate:
    """A single stock item before CLIP ranking.

    ``preview_url`` is what we download and embed (photo URL or video frame).
    ``media_url`` is the full-resolution asset used downstream for rendering.
    """

    platform: str
    external_id: str
    kind: MediaKind
    preview_url: str
    media_url: str
    attribution_name: str | None = None
    attribution_url: str | None = None
    license: str | None = None
    duration: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class StockSource(ABC):
    """One searchable media provider (Pexels, Wikimedia, stub for tests, ...)."""

    name: str
    # The provider string written onto Candidate.platform (and the assets cache).
    # Multiple sources can share a platform, e.g. pexels_photo/pexels_video -> "pexels".
    platform: str
    requires_key: bool
    media_kinds: tuple[MediaKind, ...]

    @abstractmethod
    async def search(
        self,
        query: str,
        n: int,
        credentials: dict[str, str | None],
        options: dict[str, Any],
        *,
        http_client: Any,
    ) -> list[Candidate]:
        """Return up to ``n`` candidates for ``query``.

        ``http_client`` is an ``httpx.AsyncClient`` passed in by the pipeline so
        sources do not create their own clients per call.
        """
