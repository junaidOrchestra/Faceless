"""Transcriber abstraction — audio path to word-timestamped beats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class WordSpan:
    """One transcribed word with timing and a filler/hesitation flag."""

    text: str
    start_s: float
    end_s: float
    is_filler: bool = False


@dataclass(slots=True)
class BeatSegment:
    index: int
    text: str
    start_s: float
    end_s: float
    # Per-word timing within this beat (empty when the recognizer gave none).
    words: list[WordSpan] = field(default_factory=list)


class Transcriber(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: str) -> list[BeatSegment]:
        """Return narration beats with word-level timing aggregated per beat."""
