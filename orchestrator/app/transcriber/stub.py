"""Stub transcriber for tests."""

from __future__ import annotations

from .base import BeatSegment, Transcriber, WordSpan
from .fillers import is_filler


def _words(text: str, start: float, end: float) -> list[WordSpan]:
    """Evenly space ``text`` across ``[start, end]`` with filler flags."""

    tokens = text.split()
    if not tokens:
        return []
    step = (end - start) / len(tokens)
    spans: list[WordSpan] = []
    for i, tok in enumerate(tokens):
        w_start = start + i * step
        spans.append(
            WordSpan(
                text=tok,
                start_s=w_start,
                end_s=w_start + step,
                is_filler=is_filler(tok),
            )
        )
    return spans


class StubTranscriber(Transcriber):
    async def transcribe(self, audio_path: str) -> list[BeatSegment]:
        del audio_path
        beats = [
            (0, "The sun rises, um, over quiet mountains.", 0.0, 3.0),
            (1, "What does tomorrow bring?", 3.0, 6.0),
        ]
        return [
            BeatSegment(i, text, start, end, words=_words(text, start, end))
            for i, text, start, end in beats
        ]
