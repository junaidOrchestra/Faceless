"""Cerebras LLM provider via the OpenAI-compatible chat completions API.

Cerebras serves an OpenAI-compatible endpoint, so we call it with plain ``httpx``
(already a dependency) instead of pulling in another SDK. Both calls request a
JSON object response and parse it into our typed dataclasses.

For ``gpt-oss-120b`` we pass ``reasoning_effort`` and ``max_completion_tokens``
directly in the request body (over raw HTTP these are accepted as standard
parameters). Requests that time out or fail to connect are retried with capped
exponential backoff — by default indefinitely — so a slow/cold endpoint does not
fail the whole video job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from .base import BeatQueryPlan, LLMProvider, Vocabulary

logger = logging.getLogger(__name__)


class CerebrasLLMProvider(LLMProvider):
    """LLM provider backed by Cerebras inference (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-oss-120b",
        base_url: str = "https://api.cerebras.ai/v1",
        *,
        max_tokens: int = 8192,
        reasoning_effort: str = "low",
        timeout_s: float = 60.0,
        max_retries: int = 0,
        retry_backoff_s: float = 2.0,
        retry_backoff_max_s: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._timeout_s = timeout_s
        # ``max_retries == 0`` means retry timeouts forever (per user request).
        self._max_retries = max_retries
        self._retry_backoff_s = retry_backoff_s
        self._retry_backoff_max_s = retry_backoff_max_s

    async def vocabulary(self, transcript: str) -> Vocabulary:
        prompt = (
            "Extract visual vocabulary from this narration transcript. "
            "Respond with a JSON object: "
            '{"topic": str, "subjects": [str], "metaphors": [str]}.\n\n'
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
            "Respond with a JSON object: "
            '{"beats": [{"visual_queries": [str], "metaphor_queries": [str], '
            '"is_rhetorical": bool, "text_overlay": str|null}]} '
            "with one entry per beat, in the same order.\n"
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

    async def _generate_json(self, prompt: str) -> dict[str, Any]:
        """Call chat completions with retry-on-timeout and parse a JSON object."""

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful assistant that replies with only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            # OpenAI-compatible JSON mode; the model returns a single JSON object.
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            # gpt-oss controls: token budget (incl. reasoning) and reasoning depth.
            "max_completion_tokens": self._max_tokens,
            "reasoning_effort": self._reasoning_effort,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        content = await self._post_with_retry(payload, headers)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Some models wrap JSON in prose/code fences; salvage the object.
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                logger.warning("Cerebras returned non-JSON content; using empty result.")
                return {}
            return json.loads(match.group(0))

    async def _post_with_retry(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str:
        """POST the request, retrying timeouts/connection errors with backoff.

        Retries are unbounded when ``max_retries == 0`` (the configured default),
        so a cold or temporarily slow endpoint keeps being retried rather than
        failing the video job. HTTP error statuses (4xx/5xx) are not retried.
        """

        attempt = 0
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url, timeout=self._timeout_s
                ) as client:
                    response = await client.post(
                        "/chat/completions", json=payload, headers=headers
                    )
                    response.raise_for_status()
                    data = response.json()
                return data["choices"][0]["message"]["content"] or "{}"
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if self._max_retries and attempt >= self._max_retries:
                    logger.error(
                        "Cerebras request failed after %s attempts: %s", attempt, exc
                    )
                    raise
                delay = min(
                    self._retry_backoff_s * (2 ** (attempt - 1)),
                    self._retry_backoff_max_s,
                )
                logger.warning(
                    "Cerebras request timed out/connection error (attempt %s), "
                    "retrying in %.1fs: %s",
                    attempt,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
