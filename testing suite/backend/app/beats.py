"""Enrich the orchestrator's raw beats for the UI's per-beat inspector.

For each beat we surface: the transcript text + timing, the keywords sent to the
clip server, the beat's visual TYPE (personality / event / general), and which
clip-server SOURCES it routes to (mirroring the orchestrator's per-beat routing
in orchestrator/app/pipeline.py).
"""

from __future__ import annotations

from typing import Any

from .config import Settings
from .orchestrator_client import parse_sources

# orchestrator VisualType -> (UI label, coarse bucket key).
_TYPE_MAP: dict[str, tuple[str, str]] = {
    "person": ("Personality", "personality"),
    "event": ("Event", "event"),
    "broll": ("General (b-roll)", "general"),
    "symbolic": ("General (symbolic)", "general"),
}


def _routed_sources(visual_type: str, settings: Settings) -> list[str]:
    """Which clip-server sources this beat's type routes to (display only)."""
    if visual_type == "person":
        return parse_sources(settings.person_sources)
    if visual_type == "event":
        return parse_sources(settings.event_sources)
    return parse_sources(settings.sources)


def enrich_beat(raw: dict[str, Any], settings: Settings) -> dict[str, Any]:
    q = raw.get("queries") or {}
    visual_type = str(q.get("visual_type") or "broll").lower()
    label, bucket = _TYPE_MAP.get(visual_type, ("General", "general"))

    # ``keywords`` is exactly what the orchestrator sends to the clip server;
    # fall back to the raw visual queries if an older job didn't store them.
    keywords = q.get("keywords") or q.get("visual") or []
    keywords = [str(k) for k in keywords if str(k).strip()]

    candidates = raw.get("candidates") or []
    selected = next((c for c in candidates if c.get("selected")), None)
    if selected is None and candidates:
        selected = candidates[0]

    return {
        "index": raw.get("index"),
        "text": raw.get("text") or "",
        "start_s": raw.get("start_s"),
        "end_s": raw.get("end_s"),
        "visual_type": visual_type,
        "type_label": label,
        "type_bucket": bucket,
        "keywords": keywords,
        "metaphor": [str(k) for k in (q.get("metaphor") or []) if str(k).strip()],
        "prefers_video": bool(q.get("prefers_video")),
        "theme": q.get("theme"),
        "sources": _routed_sources(visual_type, settings),
        "candidate_count": len(candidates),
        "selected_platform": (selected or {}).get("platform"),
        "selected_kind": (selected or {}).get("kind"),
        "selected_preview": (selected or {}).get("preview_url"),
    }


def enrich_beats(raw_beats: list[dict[str, Any]], settings: Settings) -> list[dict[str, Any]]:
    return [enrich_beat(b, settings) for b in raw_beats]
