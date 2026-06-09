"""Video renderer abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TimelineBeat:
    start_s: float
    end_s: float
    kind: str  # photo | video | text
    media_url: str | None
    text_overlay: str | None = None  # text card body, or optional stock overlay
    is_rhetorical: bool = False
    # In-point (seconds) to seek to within ``media_url`` before trimming. Set for
    # user-supplied source video so each beat shows its own slice; ``None`` for
    # stock clips, which always start from the top (and may loop to fill).
    source_in_s: float | None = None


class Renderer(ABC):
    @abstractmethod
    async def render(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
        *,
        width: int = 1280,
        height: int = 720,
    ) -> str:
        """Render the final MP4 at ``width``x``height`` and return the output path."""
