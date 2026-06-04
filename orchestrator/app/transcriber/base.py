"""Transcriber abstraction — audio path to word-timestamped beats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class BeatSegment:
    index: int
    text: str
    start_s: float
    end_s: float


class Transcriber(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: str) -> list[BeatSegment]:
        """Return narration beats with word-level timing aggregated per beat."""
