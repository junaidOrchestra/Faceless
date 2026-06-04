"""LLM provider abstraction — vocabulary + per-beat queries in batched calls."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Vocabulary:
    """Global visual vocabulary extracted from the full transcript."""

    topic: str
    subjects: list[str] = field(default_factory=list)
    metaphors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BeatQueryPlan:
    """LLM output for one beat (batched across all beats in one call)."""

    visual_queries: list[str] = field(default_factory=list)
    metaphor_queries: list[str] = field(default_factory=list)
    is_rhetorical: bool = False
    text_overlay: str | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def vocabulary(self, transcript: str) -> Vocabulary:
        """Single call: derive topic/subjects/metaphors from the transcript."""

    @abstractmethod
    async def beat_queries(
        self,
        beats: list[dict[str, Any]],
        context: Vocabulary,
    ) -> list[BeatQueryPlan]:
        """Single batched call returning one plan per beat (same order as input)."""
