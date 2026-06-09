"""Phase-2 "visual director": decide WHAT TO SHOW for each narration beat.

This module is provider-agnostic. It defines:

* the strict structured-output schema (:class:`BeatVisual` / :class:`BeatVisuals`)
  used with Cerebras gpt-oss-120b ``response_format={"type":"json_schema",...}``,
* the system prompt (:data:`VISUAL_DIRECTOR_SYSTEM`), and
* the per-job user-prompt builder (:func:`visual_director_user_prompt`).

The schema root is an OBJECT (``{"beats": [...]}``) — OpenAI/Cerebras strict
structured outputs reject a top-level array. ``extra="forbid"`` makes every model
emit ``additionalProperties: false``, and keeping all fields required (no
defaults) makes them appear in the schema's ``required`` list, both of which the
strict validator demands.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class VisualType(str, Enum):
    """The kind of visual to show for a beat (checked in priority order).

    Deliberately small: every beat gets a concrete stock search. Text is only a
    renderer fallback when no image/video asset is found.
    """

    person = "person"        # a REAL, named individual (leader, celebrity, figure)
    event = "event"          # a SPECIFIC, named historical event
    broll = "broll"          # concrete, filmable thing or action
    symbolic = "symbolic"    # abstract idea -> concrete stand-in


class BeatVisual(BaseModel):
    """One beat's visual decision. All fields required for strict structured output."""

    model_config = ConfigDict(extra="forbid")

    index: int
    visual_type: VisualType
    queries: list[str]      # broll/symbolic: 1-3 short stock-search phrases
    overlay: str            # kept for schema compatibility; must be "" (no text on media)
    prefers_video: bool     # broll only: motion + long enough


class BeatVisuals(BaseModel):
    """Object root wrapping the per-beat list (required by strict structured output)."""

    model_config = ConfigDict(extra="forbid")

    beats: list[BeatVisual]


# NOTE: This is the ACTIVE prompt. The previous (pre-editorial) version is kept
# verbatim in ``visual_director_legacy.py`` so this change can be reverted easily.
VISUAL_DIRECTOR_SYSTEM = (
    "You are a video editor deciding WHAT TO SHOW for each line of a narration.\n\n"
    "You are given the video's TOPIC, its SUBJECTS, and its METAPHORS (a shared "
    "visual palette), and a numbered list of BEATS (each with its duration). For "
    "EVERY beat, return one object: a visual_type, search queries, an empty "
    "overlay, and prefers_video.\n\n"
    "There are FOUR visual types. Pick the FIRST that fits:\n"
    "1. person     - the line names a REAL, SPECIFIC, NAMEABLE individual: a "
    "historical personality, world leader, head of state, politician, or well-known "
    "public figure/celebrity (e.g. 'Winston Churchill', 'Nelson Mandela', 'Barack "
    "Obama', 'Albert Einstein'). These need REAL, authentic photographs of THAT "
    "person, not generic stock. Choose this WHENEVER a real named individual is "
    "present, in preference to broll.\n"
    "2. event      - the line names a SPECIFIC, NAMED historical event (e.g. 'the "
    "fall of the Berlin Wall', 'D-Day landings', 'the 1969 Moon landing', 'the "
    "Chernobyl disaster'). These need REAL, authentic archive photographs of THAT "
    "event, not generic stock. Choose this WHENEVER a named real event is present "
    "(and no specific person dominates the line), in preference to broll.\n"
    "3. broll      - the line names or implies a real, filmable thing, place, "
    "or action with NO specific named person/event (a port, a drone, troops, a "
    "handshake, flags, a signing). Prefer this when any concrete generic visual "
    "exists and there is no nameable person/event.\n"
    "4. symbolic   - the line is abstract with no filmable subject; stand in with a "
    "COMMON, real-world object or scene that stock libraries are FULL of (a "
    "handshake, a chess board, a balance scale, a locked gate, stacks of cash, a "
    "tightrope walker). Even pure rhetorical lines become a symbolic search; never "
    "a text card.\n\n"
    "PERSON / EVENT queries = THE EXACT NAME. For a person or event beat, the "
    "queries must be the literal proper name(s): the person's full name, or the "
    "event's common name (optionally with its year). Do NOT translate a named "
    "person/event into a generic scene. GOOD: ['Margaret Thatcher'], ['Berlin Wall "
    "1989'], ['Apollo 11 Moon landing']. BAD: ['woman politician'], ['concrete "
    "wall'], ['astronaut']. Give 1-2 name variants at most (e.g. ['John F. "
    "Kennedy', 'JFK']). prefers_video is ALWAYS false for person/event (we use "
    "photographs).\n\n"
    "THE ONE RULE FOR broll/symbolic queries = SEARCHABILITY. Every query must be "
    "something a "
    "photographer could literally point a camera at and that ALREADY EXISTS by the "
    "thousands on Pexels/Pixabay. Use plain, common, CONCRETE nouns: people, "
    "objects, places, vehicles, actions. Before you emit a query, apply this test: "
    "'Would typing this into a stock photo site return many real photos?' If not, "
    "rewrite it into the THING you would actually see.\n"
    "- BANNED as queries: abstract nouns, jargon, and coined phrases. Words such as "
    "posture, doctrine, alignment, leverage, stability, strategy, security, "
    "solidarity, partnership, sentiment, order, dominance, legitimacy, era - and "
    "invented combos like 'split posture' or 'two-sided mask' - return garbage. "
    "Never use them.\n"
    "- Convert the idea into a visible scene. Rewrite pattern (concept -> what you "
    "shoot):\n"
    "   'public alignment' / 'pro-Palestine stance' -> 'protest crowd', 'flag rally'\n"
    "   'security doctrine' / 'border posture'       -> 'soldiers patrol', 'border fence'\n"
    "   'lost its strategic backer'                  -> 'leaders handshake', 'empty chair'\n"
    "   'leverage' / 'the logic of power'            -> 'chess board', 'hand on lever'\n"
    "   'intelligence dominance'                     -> 'control room screens', 'satellite dish'\n"
    "   'structural alignment'                       -> 'steel beams', 'bridge construction'\n"
    "- Name the SPECIFIC symbol, not a generic one. If the line names a cause, "
    "country, group, or institution, put THAT in the query: 'pro-Palestine' -> "
    "'Palestine flag protest' (NOT a bare 'protest crowd'); 'American power' -> "
    "'US Capitol' (NOT 'tall building'); 'the UN' -> 'UN headquarters'.\n"
    "- Prefer the SIMPLE common word over a clever one: 'handshake' beats "
    "'diplomatic rapprochement'; 'soldiers' beats 'military posture'. Generic, "
    "literal queries get the best stock matches.\n\n"
    "THEME = tie every query to THIS video. Use TOPIC, SUBJECTS, and METAPHORS so "
    "visuals stay on-subject: with an India-Israel security topic, troops -> "
    "'Indian soldiers' / 'Israeli soldiers', a deal -> 'India Israel flags' / "
    "'leaders handshake'. REUSE a SUBJECT or METAPHOR phrase whenever it fits. "
    "Lines about PLACES become a concrete visual of them (flags, leaders, a border, "
    "soldiers), NOT a map. Lines about a YEAR or event become an evocative real "
    "photo (e.g. 'Soviet flag', 'diplomats signing', 'old newspaper'). NEVER return "
    "a bare number, a country pair, or caption text.\n\n"
    "Fill the fields like this:\n"
    "- queries       : 1-3 SHORT, concrete noun phrases (1-3 words each), each "
    "passing the searchability test above. Required for every beat.\n"
    "- overlay       : ALWAYS \"\". We do not burn text over images/videos.\n"
    "- prefers_video : true ONLY for a broll beat that shows MOTION and is at least "
    "~2.5s long; false otherwise (false for symbolic).\n\n"
    "Across the whole list: avoid the same visual_type on long runs of consecutive "
    "beats when a sensible alternative exists, and REUSE the exact same query for a "
    "recurring idea (a motif) so the same asset comes back deliberately.\n\n"
    'Return a single JSON OBJECT of the form {"beats": [ ... ]} with one element per '
    "beat, in order, echoing each beat's index. The shape is enforced for you - just "
    "choose good content.\n\n"
    "EXAMPLES (different domains on purpose - learn the pattern, not the topic). Each "
    'shows ONE element of the "beats" array:\n\n'
    'Beat: "Churchill refused to negotiate with Hitler." (3.1s)  '
    "(named real people -> person, exact names)\n"
    '{"index":0,"visual_type":"person","queries":["Winston Churchill","Adolf Hitler"],'
    '"overlay":"","prefers_video":false}\n\n'
    'Beat: "The Berlin Wall finally came down in 1989." (3.0s)  '
    "(named historical event -> event)\n"
    '{"index":1,"visual_type":"event","queries":["Berlin Wall fall 1989"],'
    '"overlay":"","prefers_video":false}\n\n'
    'Beat: "Wind turbines now generate half the region\'s electricity." (3.4s)\n'
    '{"index":0,"visual_type":"broll","queries":["wind turbines","power grid"],'
    '"overlay":"","prefers_video":true}\n\n'
    'Beat: "By 2023 sales had tripled." (2.6s)  (a year -> concrete visual, no text)\n'
    '{"index":1,"visual_type":"broll","queries":["factory assembly line"],'
    '"overlay":"","prefers_video":false}\n\n'
    'Beat: "Goods move from China to Europe." (3.0s)  (places -> concrete, not a map)\n'
    '{"index":2,"visual_type":"broll","queries":["cargo ship port","shipping containers"],'
    '"overlay":"","prefers_video":true}\n\n'
    'Beat: "The Soviet Union collapsed in 1991." (2.2s)  (event -> evocative still)\n'
    '{"index":3,"visual_type":"broll","queries":["Soviet flag","Kremlin"],'
    '"overlay":"","prefers_video":false}\n\n'
    'Beat: "It was a calculated bet." (2.4s)  (abstract -> common stock object)\n'
    '{"index":4,"visual_type":"symbolic","queries":["chess board","poker chips"],'
    '"overlay":"","prefers_video":false}\n\n'
    'Beat: "It came down to security doctrine, not sentiment." (3.0s)  '
    "(jargon BANNED -> shoot the thing)\n"
    '{"index":5,"visual_type":"broll","queries":["soldiers patrol","border fence"],'
    '"overlay":"","prefers_video":true}\n\n'
    'Beat: "Publicly it stayed pro-Palestine." (2.8s)  '
    "(name the SPECIFIC symbol, not a generic crowd)\n"
    '{"index":6,"visual_type":"broll","queries":["Palestine flag protest"],'
    '"overlay":"","prefers_video":false}\n\n'
    'Beat: "It was never about speed. It was about trust." (2.8s)  (maxim -> common object)\n'
    '{"index":7,"visual_type":"symbolic","queries":["handshake","rope bridge"],'
    '"overlay":"","prefers_video":false}'
)


def visual_director_user_prompt(
    beats: list[dict[str, Any]],
    *,
    topic: str,
    subjects: list[str],
    metaphors: list[str],
) -> str:
    """Build the user message for one batched visual-director call.

    ``beats`` items use the orchestrator beat shape: ``index``, ``text`` and
    ``start_s``/``end_s`` (duration is derived). Index is echoed so results can be
    matched back by index rather than array position.
    """

    subjects_line = ", ".join(subjects) or "(none)"
    metaphors_line = ", ".join(metaphors) or "(none)"
    lines: list[str] = []
    for i, beat in enumerate(beats):
        index = beat.get("index", i)
        text = str(beat.get("text", "")).replace("\n", " ").strip()
        duration = float(beat.get("end_s", 0.0)) - float(beat.get("start_s", 0.0))
        lines.append(f"{index}: {text} ({duration:.1f}s)")
    beats_block = "\n".join(lines)
    return (
        f"TOPIC: {topic}\n"
        f"SUBJECTS: {subjects_line}\n"
        f"METAPHORS: {metaphors_line}\n\n"
        f"BEATS (one per line, 'index: text (duration)'):\n{beats_block}"
    )


def beat_visuals_schema() -> dict[str, Any]:
    """JSON schema for the strict ``response_format`` (object root)."""

    return BeatVisuals.model_json_schema()


# ---------------------------------------------------------------------------
# Light cleanup pass (LLM -> renderer)
# ---------------------------------------------------------------------------
#
# With the map/data/archival/text-card logic removed, classification is simple,
# so this pass only does mechanical hygiene: trim + dedupe queries, drop blanks,
# clear overlays, and keep ``prefers_video`` limited to broll.


def _clean_phrase(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _dedupe_queries(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        phrase = _clean_phrase(raw)
        key = phrase.lower()
        if phrase and key not in seen:
            seen.add(key)
            out.append(phrase)
    return out


def normalize_beat_visuals(
    visuals: list[BeatVisual],
    beats: list[dict[str, Any]] | None = None,
) -> list[BeatVisual]:
    """Clean classifier output before it reaches the renderer.

    Returns a new list (input is not mutated). A query-less beat is left as-is;
    the pipeline's subject fallback fills it in. ``beats`` is accepted for
    signature compatibility but unused.
    """

    fixed: list[BeatVisual] = []
    for v in visuals:
        queries = _dedupe_queries(v.queries)
        prefers_video = bool(v.prefers_video) and v.visual_type == VisualType.broll
        fixed.append(
            v.model_copy(
                update={
                    "queries": queries,
                    "overlay": "",
                    "prefers_video": prefers_video,
                }
            )
        )
    return fixed
