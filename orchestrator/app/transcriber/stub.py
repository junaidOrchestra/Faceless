"""Stub transcriber for tests."""

from __future__ import annotations

from .base import BeatSegment, Transcriber


class StubTranscriber(Transcriber):
    async def transcribe(self, audio_path: str) -> list[BeatSegment]:
        del audio_path
        return [
            BeatSegment(0, "The sun rises over quiet mountains.", 0.0, 3.0),
            BeatSegment(1, "What does tomorrow bring?", 3.0, 6.0),
        ]
