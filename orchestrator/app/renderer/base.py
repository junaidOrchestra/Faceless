"""Video renderer abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..timeline import AudioPiece


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
    # When True, this beat's source clip carries its own audio (e.g. the per-word
    # SFX of an animated text card) which should be MIXED into the final track at
    # the beat's timeline offset, on top of the narration. The clip's video is
    # used for the segment as usual; only its audio is additionally mixed.
    mix_audio: bool = False


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
        audio_windows: list[tuple[float, float]] | None = None,
        audio_pieces: list[AudioPiece] | None = None,
    ) -> str:
        """Render the final MP4 at ``width``x``height`` and return the output path.

        When ``audio_pieces`` is set it takes precedence and the narration track is
        re-assembled from that ordered list (narration slices + silent gaps for
        standalone inserted beats). Otherwise, when ``audio_windows`` is set, only
        those ``(start_s, end_s)`` slices of ``audio_path`` are stitched in order.
        When both are ``None``, the full narration file is muxed as-is.
        """
