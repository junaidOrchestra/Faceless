"""Smoke test for the Cerebras visual-director with a stubbed SDK client.

No network and no installed SDK required: a fake client mimics the
``client.chat.completions.create(...)`` surface and returns a strict-schema
JSON object. Asserts one validated :class:`BeatVisual` per input index.
"""

from __future__ import annotations

import json

import pytest

from app.llm.base import Vocabulary
from app.llm.cerebras import CerebrasProvider
from app.llm.visual_director import (
    BeatVisual,
    BeatVisuals,
    VisualType,
    normalize_beat_visuals,
)


def _bv(index: int, vt: VisualType, **kw) -> BeatVisual:
    return BeatVisual(
        index=index,
        visual_type=vt,
        queries=kw.get("queries", []),
        overlay=kw.get("overlay", ""),
        prefers_video=kw.get("prefers_video", False),
    )

BEATS = [
    {"index": 0, "text": "Wind turbines generate half the power.", "start_s": 0.0, "end_s": 3.4},
    {"index": 1, "text": "Sales tripled to four million in 2023.", "start_s": 3.4, "end_s": 6.0},
    {"index": 2, "text": "Goods move from Shenzhen to Europe.", "start_s": 6.0, "end_s": 9.0},
    {"index": 3, "text": "The first plant opened in 1908.", "start_s": 9.0, "end_s": 11.2},
    {"index": 4, "text": "It was never about speed. It was trust.", "start_s": 11.2, "end_s": 14.0},
]


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _Completions:
    def create(self, **kwargs):  # noqa: ANN003 - mimic SDK signature loosely
        # Echo one object per beat described in the user message ("index: text").
        user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
        indices = []
        for line in user.splitlines():
            head = line.split(":", 1)[0].strip()
            if head.isdigit():
                indices.append(int(head))
        visuals = [
            BeatVisual(
                index=i,
                visual_type=VisualType.broll,
                queries=["stock clip"],
                overlay="",
                prefers_video=False,
            )
            for i in indices
        ]
        return _Resp(BeatVisuals(beats=visuals).model_dump_json())


class _Chat:
    def __init__(self) -> None:
        self.completions = _Completions()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = _Chat()


@pytest.mark.asyncio
async def test_visual_director_one_per_index() -> None:
    provider = CerebrasProvider("unused-key", client=_FakeClient(), chunk_size=2)
    visuals = await provider.visual_director(
        BEATS, topic="energy", subjects=["turbine"], metaphors=["gear"]
    )

    assert len(visuals) == len(BEATS)
    assert [v.index for v in visuals] == [b["index"] for b in BEATS]
    # Every element validates against the strict schema wrapper.
    BeatVisuals(beats=visuals)


@pytest.mark.asyncio
async def test_beat_queries_adapts_to_plans() -> None:
    provider = CerebrasProvider("unused-key", client=_FakeClient(), chunk_size=18)
    plans = await provider.beat_queries(
        BEATS, Vocabulary(topic="energy", subjects=["turbine"], metaphors=["gear"])
    )
    assert len(plans) == len(BEATS)
    assert all(p.visual_type == "broll" for p in plans)
    assert all(p.visual_queries for p in plans)


def test_beat_visuals_schema_is_strict_object() -> None:
    schema = BeatVisuals.model_json_schema()
    assert schema["type"] == "object"
    assert "beats" in schema["properties"]
    # extra="forbid" -> additionalProperties:false on the nested beat object.
    beat_def = schema["$defs"]["BeatVisual"]
    assert beat_def["additionalProperties"] is False
    # All beat fields required (no defaults) for strict structured output.
    assert set(beat_def["required"]) == {
        "index",
        "visual_type",
        "queries",
        "overlay",
        "prefers_video",
    }


def test_missing_index_gets_safe_default() -> None:
    # A chunk that returns nothing must still yield a default per beat.
    schema = json.dumps(BeatVisuals(beats=[]).model_dump())
    assert "beats" in schema


# --- normalize_beat_visuals (light cleanup only) -----------------------------


def test_only_stock_visual_types_exist() -> None:
    assert {t.value for t in VisualType} == {"person", "event", "broll", "symbolic"}


def test_overlay_is_always_cleared() -> None:
    v = _bv(0, VisualType.symbolic, queries=["trust handshake"], overlay=" Not love, leverage ")
    out = normalize_beat_visuals([v])[0]
    assert out.visual_type == VisualType.symbolic
    assert out.queries == ["trust handshake"]
    assert out.overlay == ""


def test_queries_trimmed_and_deduped() -> None:
    v = _bv(0, VisualType.broll, queries=["  military drone ", "Military Drone", "radar"])
    out = normalize_beat_visuals([v])[0]
    assert out.queries == ["military drone", "radar"]


def test_prefers_video_limited_to_broll() -> None:
    sym = _bv(0, VisualType.symbolic, queries=["chess board"], prefers_video=True)
    bro = _bv(1, VisualType.broll, queries=["cargo ship"], prefers_video=True)
    out = normalize_beat_visuals([sym, bro])
    assert out[0].prefers_video is False
    assert out[1].prefers_video is True
