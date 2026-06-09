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


# Visual treatment a beat is classified into (priority order, first match wins).
# Simplified set: every beat is a concrete stock search (broll/symbolic). No
# planned text cards, map/data/archival special-casing, or text overlays.
VISUAL_TYPES: tuple[str, ...] = (
    "person",      # real, named individual -> authentic photos (Openverse/Flickr)
    "event",       # specific named historical event -> archive photos
    "broll",       # concrete, filmable thing/action -> stock B-roll
    "symbolic",    # abstract idea -> concrete stand-in stock search
    "fallback",    # none of the above -> symbolic stock search
)


@dataclass(slots=True)
class BeatQueryPlan:
    """LLM output for one beat (batched across all beats in one call)."""

    visual_queries: list[str] = field(default_factory=list)
    metaphor_queries: list[str] = field(default_factory=list)
    is_rhetorical: bool = False
    text_overlay: str | None = None
    # --- Visual director classification ---------------------------------------
    visual_type: str = "broll"
    spec: str | None = None  # primary stock query for inspection/debug output
    overlay: str | None = None  # kept for legacy providers; stock media should not use it
    prefers_video: bool = False  # for B-roll: motion matters vs. quick still


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

    async def theme_keywords(
        self,
        theme: str,
        count: int,
        *,
        examples: list[str] | None = None,
    ) -> list[str]:
        """Return up to ``count`` stock-search phrases for a single visual THEME.

        Used by vibe-mode (the user picked a vibe instead of "match my script"),
        where visuals come from the theme rather than the transcript. ``examples``
        are representative phrases that steer the model. Implementations may return
        fewer than ``count`` (the caller tops up from a curated seed list). The
        default returns nothing so providers without a structured-output path
        simply fall back to the seed keywords.
        """

        del theme, count, examples
        return []
