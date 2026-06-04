"""Deterministic LLM stub for tests."""

from __future__ import annotations

from typing import Any

from .base import BeatQueryPlan, LLMProvider, Vocabulary


class StubLLMProvider(LLMProvider):
    async def vocabulary(self, transcript: str) -> Vocabulary:
        return Vocabulary(
            topic="stub-topic",
            subjects=["nature", "city"],
            metaphors=["journey", "light"],
        )

    async def beat_queries(
        self,
        beats: list[dict[str, Any]],
        context: Vocabulary,
    ) -> list[BeatQueryPlan]:
        del context
        plans: list[BeatQueryPlan] = []
        for beat in beats:
            text = beat.get("text", "")
            plans.append(
                BeatQueryPlan(
                    visual_queries=[f"{text[:32]} scenery"],
                    metaphor_queries=["abstract gradient"],
                    is_rhetorical=text.strip().endswith("?"),
                    text_overlay=text[:48] if text.strip().endswith("?") else None,
                )
            )
        return plans
