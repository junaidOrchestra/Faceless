"""Stub renderer — writes a tiny placeholder MP4 without FFmpeg."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..timeline import AudioPiece
from .base import Renderer, TimelineBeat


class StubRenderer(Renderer):
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
        del audio_path, timeline, width, height, audio_windows, audio_pieces

        def _write() -> str:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Not a valid MP4, but sufficient for smoke tests that only check status.
            path.write_bytes(b"STUB_MP4")
            return str(path)

        return await asyncio.to_thread(_write)
