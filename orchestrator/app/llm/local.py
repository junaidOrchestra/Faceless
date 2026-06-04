"""Local GGUF LLM via llama-cpp-python (batched JSON-ish responses)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .base import BeatQueryPlan, LLMProvider, Vocabulary

logger = logging.getLogger(__name__)


class LocalLLMProvider(LLMProvider):
    def __init__(self, model_path: str) -> None:
        from llama_cpp import Llama

        self._llm = Llama(model_path=model_path, n_ctx=4096, verbose=False)

    async def vocabulary(self, transcript: str) -> Vocabulary:
        prompt = (
            "Return JSON only: {\"topic\":\"...\",\"subjects\":[],\"metaphors\":[]}\n"
            f"Transcript:\n{transcript[:8000]}"
        )
        raw = self._complete(prompt)
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
            "Return JSON only: {\"beats\":[{\"visual_queries\":[],\"metaphor_queries\":[],"
            "\"is_rhetorical\":false,\"text_overlay\":null}]}\n"
            f"Context: {context}\nBeats: {beats}"
        )
        raw = self._complete(prompt)
        rows = raw.get("beats") or []
        plans = [
            BeatQueryPlan(
                visual_queries=list(r.get("visual_queries") or ["background"]),
                metaphor_queries=list(r.get("metaphor_queries") or []),
                is_rhetorical=bool(r.get("is_rhetorical")),
                text_overlay=r.get("text_overlay"),
            )
            for r in rows
        ]
        while len(plans) < len(beats):
            plans.append(BeatQueryPlan(visual_queries=["background"]))
        return plans[: len(beats)]

    def _complete(self, prompt: str) -> dict[str, Any]:
        out = self._llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = out["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        return json.loads(match.group(0))
