"""Gemini LLM provider via google-genai with JSON response schema."""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import BeatQueryPlan, LLMProvider, Vocabulary

logger = logging.getLogger(__name__)


class GeminiLLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def vocabulary(self, transcript: str) -> Vocabulary:
        prompt = (
            "Extract visual vocabulary from this narration transcript. "
            "Return JSON: {topic, subjects[], metaphors[]}.\n\n"
            f"{transcript[:12000]}"
        )
        raw = await self._generate_json(prompt)
        return Vocabulary(
            topic=str(raw.get("topic", "general")),
            subjects=list(raw.get("subjects") or []),
            metaphors=list(raw.get("metaphors") or []),
        )

    async def beat_queries(
        self,
        beats: list[dict[str, Any]],
        context: Vocabulary,
    ) -> list[BeatQueryPlan]:
        prompt = (
            "For each beat, propose stock-footage search queries. "
            "Return JSON: {beats: [{visual_queries[], metaphor_queries[], "
            "is_rhetorical, text_overlay}]} in the same order.\n"
            f"Context: {context}\nBeats: {beats}"
        )
        raw = await self._generate_json(prompt)
        rows = raw.get("beats") or []
        plans: list[BeatQueryPlan] = []
        for row in rows:
            plans.append(
                BeatQueryPlan(
                    visual_queries=list(row.get("visual_queries") or ["nature"]),
                    metaphor_queries=list(row.get("metaphor_queries") or []),
                    is_rhetorical=bool(row.get("is_rhetorical")),
                    text_overlay=row.get("text_overlay"),
                )
            )
        # Pad/truncate to match beat count if the model drifts.
        while len(plans) < len(beats):
            plans.append(BeatQueryPlan(visual_queries=["abstract background"]))
        return plans[: len(beats)]

    async def theme_keywords(
        self,
        theme: str,
        count: int,
        *,
        examples: list[str] | None = None,
    ) -> list[str]:
        n = max(1, count)
        example_line = (
            f"Example phrases: {', '.join(examples)}.\n" if examples else ""
        )
        prompt = (
            "Generate stock-footage search phrases for a single visual THEME. "
            'Return JSON {"keywords": [str]} with exactly '
            f"{n} varied phrases, each 1-3 plain concrete words that return many "
            "videos on Pexels and clearly belong to the theme. Cover different "
            "sub-scenes; avoid duplicates and abstract words.\n"
            f"THEME: {theme}\n{example_line}"
        )
        try:
            raw = await self._generate_json(prompt)
        except Exception as exc:  # noqa: BLE001 - fall back to the curated seed list
            logger.warning("theme_keywords failed for %r: %s", theme, exc)
            return []
        out: list[str] = []
        seen: set[str] = set()
        for kw in raw.get("keywords") or []:
            cleaned = " ".join(str(kw).split()).strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                seen.add(key)
                out.append(cleaned)
        return out[:n]

    async def _generate_json(self, prompt: str) -> dict[str, Any]:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        text = response.text or "{}"
        return json.loads(text)
