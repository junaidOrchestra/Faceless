"""Cerebras LLM provider (gpt-oss-120b) via the official ``cerebras-cloud-sdk``.

Two batched calls per video:

* :meth:`CerebrasProvider.vocabulary` — derive topic/subjects/metaphors from the
  full transcript (JSON-object response).
* :meth:`CerebrasProvider.visual_director` — the Phase-2 "what to show" decision
  per beat, using STRICT structured output (``response_format`` with the
  :class:`BeatVisuals` JSON schema) so the result always validates.

``beat_queries`` adapts the visual-director output into the legacy
:class:`BeatQueryPlan` the rest of the pipeline already consumes, so rendering is
unchanged while the richer classification is available for inspection/routing.

gpt-oss is a reasoning model: reasoning tokens share ``max_tokens``. We keep
``reasoning_effort="low"`` and CHUNK beats into small batches so a response never
risks truncation; a truncated chunk (``finish_reason == "length"``) is retried
with a smaller size, and any missing index gets a safe default rather than failing
the whole video. The API key is never logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from typing import Any, Callable

from .base import BeatQueryPlan, LLMProvider, Vocabulary
from .visual_director import (
    VISUAL_DIRECTOR_SYSTEM,
    BeatVisual,
    BeatVisuals,
    VisualType,
    beat_visuals_schema,
    normalize_beat_visuals,
    visual_director_user_prompt,
)

logger = logging.getLogger(__name__)


_VOCABULARY_SYSTEM = (
    "You analyse a narration transcript and return STRICT JSON.\n"
    "Return an object: "
    '{"topic": str, "subjects": [str], "metaphors": [str]}.\n'
    "- topic: ONE short sentence describing what the whole video is about "
    "(subject + angle).\n"
    "- subjects: 8 to 12 recurring stock-footage search phrases a video editor "
    "would type into Pexels/Unsplash to fetch B-roll.\n"
    "- metaphors: 0 to 4 concrete visual stand-ins for abstract ideas in the "
    "narration (e.g. 'chess board' for strategy, 'cracked wall' for division).\n"
    "Rules for subjects/metaphors phrases:\n"
    "- 1 to 3 words. Concrete nouns or noun + simple modifier.\n"
    "  GOOD: 'oil refinery', 'dollar bills', 'Indian flag', 'military drone'.\n"
    "  BAD: long scene descriptions, 'alignment' (too abstract), '1991' (not "
    "filmable).\n"
    "- No years, no counts, no abstract nouns alone, no full-sentence scene "
    "descriptions."
)


# Unicode dashes the model sometimes emits that search poorly on stock sites —
# normalize them to a plain ASCII hyphen.
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2212"


def _clean_query(value: Any) -> str:
    """Normalize one query string: ASCII dashes, collapse whitespace, trim."""

    text = unicodedata.normalize("NFKC", str(value))
    for dash in _DASHES:
        text = text.replace(dash, "-")
    return " ".join(text.split()).strip()


def _clean_queries(values: Any) -> list[str]:
    """Clean a list of queries, dropping blanks and exact duplicates (order-stable)."""

    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        cleaned = _clean_query(raw)
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


# Map the visual-director enum to the legacy BeatQueryPlan.visual_type string.
_VTYPE_TO_PLAN = {
    VisualType.broll: "broll",
    VisualType.symbolic: "symbolic",
}

# Types that actually issue a stock search (need at least one query phrase).
_SEARCH_TYPES = {VisualType.broll, VisualType.symbolic}


class _Truncated(Exception):
    """Raised when a chunk response hit the token limit (finish_reason=length)."""


class CerebrasProvider(LLMProvider):
    """LLM provider backed by Cerebras inference using the official SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-oss-120b",
        *,
        base_url: str | None = None,
        max_tokens: int = 8192,
        reasoning_effort: str = "low",
        timeout_s: float = 60.0,
        max_retries: int = 0,
        retry_backoff_s: float = 2.0,
        retry_backoff_max_s: float = 30.0,
        chunk_size: int = 18,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort
        self._timeout_s = timeout_s
        # ``max_retries == 0`` means retry transient errors forever.
        self._max_retries = max_retries
        self._retry_backoff_s = retry_backoff_s
        self._retry_backoff_max_s = retry_backoff_max_s
        self._chunk_size = max(1, chunk_size)
        # Allow client injection for tests; otherwise build the real SDK client.
        if client is not None:
            self._client = client
        else:
            from cerebras.cloud.sdk import Cerebras

            kwargs: dict[str, Any] = {"api_key": api_key, "timeout": timeout_s}
            normalized = _normalize_base_url(base_url)
            if normalized:
                kwargs["base_url"] = normalized
            self._client = Cerebras(**kwargs)

    # --- Public API ----------------------------------------------------------

    async def vocabulary(self, transcript: str) -> Vocabulary:
        messages = [
            {"role": "system", "content": _VOCABULARY_SYSTEM},
            {"role": "user", "content": f"Narration transcript:\n\n{transcript[:12000]}"},
        ]
        content, _ = await self._complete(messages, {"type": "json_object"})
        raw = _loads_object(content)
        return Vocabulary(
            topic=str(raw.get("topic", "general")),
            subjects=list(raw.get("subjects") or []),
            metaphors=list(raw.get("metaphors") or []),
        )

    async def visual_director(
        self,
        beats: list[dict[str, Any]],
        *,
        topic: str,
        subjects: list[str],
        metaphors: list[str],
    ) -> list[BeatVisual]:
        """One visual decision per beat, batched + chunked, matched back by index."""

        results: dict[int, BeatVisual] = {}
        for start in range(0, len(beats), self._chunk_size):
            chunk = beats[start : start + self._chunk_size]
            for visual in await self._direct_chunk(chunk, topic, subjects, metaphors):
                results[visual.index] = visual

        out: list[BeatVisual] = []
        for i, beat in enumerate(beats):
            index = int(beat.get("index", i))
            visual = results.get(index)
            if visual is None:
                # Safe default: symbolic with no queries (pipeline falls back to
                # subjects/topic) rather than failing the whole video.
                logger.warning("visual_director: missing index %s; using default", index)
                visual = BeatVisual(
                    index=index,
                    visual_type=VisualType.symbolic,
                    queries=[],
                    overlay="",
                    prefers_video=False,
                )
            out.append(visual)
        # Deterministic cleanup pass: trim/dedupe queries and clear overlays.
        # Runs here so both the pipeline and the inspect tool see the corrected
        # classification.
        return normalize_beat_visuals(out, beats)

    async def beat_queries(
        self,
        beats: list[dict[str, Any]],
        context: Vocabulary,
    ) -> list[BeatQueryPlan]:
        visuals = await self.visual_director(
            beats,
            topic=context.topic,
            subjects=context.subjects,
            metaphors=context.metaphors,
        )
        subject_fallback = _clean_queries(context.subjects)[:1] or ["abstract background"]
        return [self._to_plan(v, subject_fallback) for v in visuals]

    # --- Adaptation ----------------------------------------------------------

    @staticmethod
    def _to_plan(visual: BeatVisual, subject_fallback: list[str]) -> BeatQueryPlan:
        """Adapt a :class:`BeatVisual` into the legacy :class:`BeatQueryPlan`."""

        vtype = visual.visual_type
        plan_type = _VTYPE_TO_PLAN.get(vtype, "broll")
        queries = _clean_queries(visual.queries)
        if not queries and vtype in _SEARCH_TYPES:
            queries = subject_fallback

        overlay = None
        spec = queries[0] if queries else None
        return BeatQueryPlan(
            visual_queries=queries,
            metaphor_queries=[],
            is_rhetorical=False,
            text_overlay=None,
            visual_type=plan_type,
            spec=spec,
            overlay=overlay,
            prefers_video=bool(visual.prefers_video),
        )

    # --- Structured chunk call (with truncation-aware splitting) -------------

    async def _direct_chunk(
        self,
        chunk: list[dict[str, Any]],
        topic: str,
        subjects: list[str],
        metaphors: list[str],
    ) -> list[BeatVisual]:
        if not chunk:
            return []
        messages = [
            {"role": "system", "content": VISUAL_DIRECTOR_SYSTEM},
            {
                "role": "user",
                "content": visual_director_user_prompt(
                    chunk, topic=topic, subjects=subjects, metaphors=metaphors
                ),
            },
        ]
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "beat_visuals",
                "strict": True,
                "schema": beat_visuals_schema(),
            },
        }
        try:
            content, finish_reason = await self._complete(messages, response_format)
            if finish_reason == "length":
                raise _Truncated()
            return BeatVisuals.model_validate_json(content).beats
        except _Truncated:
            if len(chunk) <= 1:
                logger.error(
                    "visual_director: single beat truncated (index=%s); using default",
                    chunk[0].get("index"),
                )
                return []
            mid = len(chunk) // 2
            logger.warning(
                "visual_director: chunk truncated (%s beats); splitting into %s + %s",
                len(chunk),
                mid,
                len(chunk) - mid,
            )
            left = await self._direct_chunk(chunk[:mid], topic, subjects, metaphors)
            right = await self._direct_chunk(chunk[mid:], topic, subjects, metaphors)
            return left + right
        except Exception as exc:  # noqa: BLE001 - bad JSON/validation must not kill the job
            logger.warning("visual_director: chunk failed to parse: %s", exc)
            return []

    # --- Low-level SDK call with retry ---------------------------------------

    async def _complete(
        self, messages: list[dict[str, str]], response_format: dict[str, Any]
    ) -> tuple[str, str | None]:
        """Run one chat-completions call; return ``(content, finish_reason)``.

        Retries transient errors (timeouts, connection errors, 429/5xx) with capped
        exponential backoff. Unbounded when ``max_retries == 0``.
        """

        def _call() -> tuple[str, str | None]:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.2,
                max_tokens=self._max_tokens,
                reasoning_effort=self._reasoning_effort,
                response_format=response_format,
            )
            choice = resp.choices[0]
            content = choice.message.content or "{}"
            return content, getattr(choice, "finish_reason", None)

        return await self._run_with_retry(_call)

    async def _run_with_retry(self, call: Callable[[], Any]) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                return await asyncio.to_thread(call)
            except Exception as exc:  # noqa: BLE001
                if not _is_retryable(exc):
                    raise
                if self._max_retries and attempt >= self._max_retries:
                    logger.error("Cerebras call failed after %s attempts: %s", attempt, exc)
                    raise
                delay = min(
                    self._retry_backoff_s * (2 ** (attempt - 1)),
                    self._retry_backoff_max_s,
                )
                logger.warning(
                    "Cerebras transient error (attempt %s), retrying in %.1fs: %s",
                    attempt,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)


# Backwards-compatible alias (factory + older imports use this name).
CerebrasLLMProvider = CerebrasProvider


def _normalize_base_url(base_url: str | None) -> str | None:
    """Strip a trailing ``/v1`` from a configured base URL.

    The Cerebras SDK's default base is ``https://api.cerebras.ai`` and it appends
    the ``/v1`` API version itself. Our config (and the older raw-httpx provider)
    used ``https://api.cerebras.ai/v1``; passing that to the SDK would produce a
    doubled ``/v1/v1/...`` path and 404. Normalize so existing env values keep
    working without manual edits.
    """

    if not base_url:
        return None
    trimmed = base_url.strip().rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed or None


def _loads_object(content: str) -> dict[str, Any]:
    """Parse a JSON object, salvaging the first {...} block if wrapped in prose."""

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            logger.warning("Cerebras returned non-JSON content; using empty result.")
            return {}
        data = json.loads(match.group(0))
    return data if isinstance(data, dict) else {}


def _is_retryable(exc: Exception) -> bool:
    """True for transient SDK/network errors worth retrying (timeouts, 429, 5xx)."""

    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in ("timeout", "connection", "ratelimit", "apiconnection"))
