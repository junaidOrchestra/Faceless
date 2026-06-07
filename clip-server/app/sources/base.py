"""Stock source abstraction and the neutral :class:`Candidate` record."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

MediaKind = Literal["photo", "video"]

# Media resolution tiers requested via JobOptions.quality. Each source maps the
# tier to the closest variant it offers. ``max`` means "largest/original
# available"; ``sd``/``hd`` target roughly this pixel width so we don't download
# 4K just to downscale it to a 1080p timeline.
_QUALITY_TARGET_WIDTH: dict[str, int] = {"sd": 960, "hd": 1920, "max": 10**9}
_DEFAULT_QUALITY = "hd"


def resolve_quality(options: dict[str, Any]) -> str:
    """Normalize ``options['quality']`` to a known tier (defaults to ``hd``)."""

    quality = str(options.get("quality") or _DEFAULT_QUALITY).lower()
    return quality if quality in _QUALITY_TARGET_WIDTH else _DEFAULT_QUALITY


def quality_target_width(options: dict[str, Any]) -> int:
    """Approximate target pixel width for the requested quality tier."""

    return _QUALITY_TARGET_WIDTH[resolve_quality(options)]


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
    # Name of the credential this source needs (looked up in the request's
    # ``credentials`` dict), e.g. "pexels" or "pixabay". ``None`` for keyless
    # sources like Wikimedia.
    credential_key: str | None = None

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
