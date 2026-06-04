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
    text_overlay: str | None = None
    is_rhetorical: bool = False


class Renderer(ABC):
    @abstractmethod
    async def render(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
    ) -> str:
        """Render the final MP4 and return the output path."""
