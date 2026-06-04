"""Turn a Whisper word stream into evenly paced, sentence-clean *visual beats*.

Why this exists
---------------
Whisper's own segments are tuned for subtitles, not visual pacing. A naive
"pack words toward a target duration" pass has a **structural bug**: it crosses
sentence boundaries, producing beats that contain the end of one sentence plus
the start of the next — two distinct ideas glued together.

The fix is an ordering rule:

    SENTENCE BOUNDARIES ARE HARD CUTS, APPLIED FIRST.

A beat must never span a sentence-ending ``.``/``?``/``!``. Only *after* splitting
into sentences do we normalize duration *within* each sentence. Duration packing
can never override a sentence boundary. The single exception is the merge step,
where an entire too-short sentence (e.g. "Fast.") may be absorbed into a
neighbor — but only as a *whole* sentence, never as a partial fragment.

Pipeline (in this exact order)
------------------------------
1. ``transcript_normalize`` — config-gated, default OFF. A no-op stub for future
   ASR cleanup.
2. Flatten words into one timestamped stream (the caller passes a flat list).
3. ``split_sentences`` — HARD sentence cut. Prefers ``pysbd`` (aligned back to
   word timestamps); falls back to a pure-stdlib rule with an abbreviation guard.
4. ``normalize_sentence`` — split each sentence to the window ``[min_s, max_s]``,
   aiming at ``target_s``, cutting at pauses then clause boundaries; never creates
   a sub-``min_s`` fragment.
5. ``merge_short_beats`` — fold sub-``min_s`` beats into the neighbor that lands
   closest to ``target_s`` (the only place a merge may cross a sentence boundary).
6. Recompute ``start_s``/``end_s``/``text`` and reindex from 0.

Everything here is pure functions over :class:`Word` records — no model calls.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# --- Lexical resources -------------------------------------------------------

# Conjunctions that make decent clause-level cut points when they *start* the
# following clause (used only as a fallback after pauses).
_CONJUNCTIONS: frozenset[str] = frozenset(
    {"and", "but", "so", "because", "which", "while", "then"}
)

_SENTENCE_TERMINALS: tuple[str, ...] = (".", "?", "!")
_CLAUSE_TERMINALS: tuple[str, ...] = (",", ";", ":")

# Closing characters that may trail terminal punctuation, e.g. ``movement.")``.
_TRAILING = "\"')]}»”’"
# Leading characters to strip when inspecting the *next* token for a conjunction.
_LEADING = "\"'([{«“‘"

# Common abbreviations that end in a period but do NOT end a sentence.
_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.",
        "etc.", "e.g.", "i.e.", "u.s.", "u.k.", "a.m.", "p.m.", "gov.",
        "sen.", "rep.", "no.", "inc.", "ltd.", "co.", "fig.", "al.", "approx.",
    }
)

# A single initial like "U." or a dotted acronym like "U.S." — not a sentence end.
_INITIALS_RE = re.compile(r"^(?:[A-Za-z]\.)+$")
# A bare enumerated number like "1." — not a sentence end (decimals like "1.5"
# never end in a period and so are unaffected).
_ENUM_NUMBER_RE = re.compile(r"^\d+\.$")

_EPS = 1e-6


# --- Data model --------------------------------------------------------------


@dataclass(slots=True)
class Word:
    """A single transcribed word with timing.

    ``text`` is kept as produced by the recognizer (it may carry a leading space),
    so beat text can be reconstructed by simple concatenation.
    """

    text: str
    start: float
    end: float


@dataclass(slots=True)
class Beat:
    """A finished visual beat: contiguous words with timing and joined text."""

    index: int
    text: str
    start_s: float
    end_s: float
    words: list[Word] = field(default_factory=list)


@dataclass(slots=True)
class SegmenterConfig:
    """Tunable thresholds for segmentation (all seconds)."""

    target_s: float = 3.5
    min_s: float = 1.5
    max_s: float = 5.0
    pause_threshold_s: float = 0.35
    # Step 1 gate: future ASR cleanup. Default OFF (no-op even when ON for now).
    normalize_transcript: bool = False
    # Prefer pysbd when available; fall back to the stdlib rule otherwise.
    use_external_segmenter: bool = True


# --- Small helpers -----------------------------------------------------------


def _duration(words: list[Word]) -> float:
    """Wall-clock span covered by a contiguous run of words."""

    if not words:
        return 0.0
    return max(0.0, words[-1].end - words[0].start)


def _beat_text(words: list[Word]) -> str:
    """Reconstruct readable beat text from its words."""

    return "".join(w.text for w in words).strip()


def _is_sentence_end(token: str) -> bool:
    """Return True if ``token`` ends a sentence, with an abbreviation guard."""

    t = token.strip().rstrip(_TRAILING)
    if not t or t[-1] not in _SENTENCE_TERMINALS:
        return False
    if t[-1] in ("?", "!"):
        return True  # never abbreviations
    # It ends in '.': screen out abbreviations, initials, and enumerations.
    low = t.lower()
    if low in _ABBREVIATIONS:
        return False
    if _INITIALS_RE.match(t):
        return False
    if _ENUM_NUMBER_RE.match(t):
        return False
    return True


# --- Step 1: optional transcript normalization (no-op stub) ------------------


def transcript_normalize(words: list[Word], config: SegmenterConfig) -> list[Word]:
    """Config-gated ASR cleanup hook. Currently a no-op (returns words as-is)."""

    if not config.normalize_transcript:
        return words
    # Intentionally a no-op for now; real ASR corrections would live here later.
    return words


# --- Step 3: hard sentence split --------------------------------------------


def _external_sentence_bounds(text: str) -> list[tuple[int, int]] | None:
    """Return char-span sentence boundaries via pysbd, or None if unavailable."""

    try:
        import pysbd
    except ImportError:
        return None
    try:
        seg = pysbd.Segmenter(language="en", clean=False, char_span=True)
        spans = seg.segment(text)
        return [(s.start, s.end) for s in spans]
    except Exception as exc:  # noqa: BLE001 - never let the segmenter crash the run
        logger.warning("pysbd failed (%s); using stdlib sentence fallback", exc)
        return None


def _split_sentences_external(
    words: list[Word], bounds: list[tuple[int, int]], token_spans: list[tuple[int, int]]
) -> list[list[Word]]:
    """Assign each word to a pysbd sentence by char-offset midpoint (monotonic)."""

    sentences: list[list[Word]] = [[] for _ in bounds]
    bi = 0
    for i, (start, end) in enumerate(token_spans):
        mid = (start + end) / 2.0
        # Advance the boundary pointer; words arrive in order so this is monotonic.
        while bi < len(bounds) - 1 and mid >= bounds[bi][1]:
            bi += 1
        sentences[bi].append(words[i])
    return [s for s in sentences if s]


def _split_sentences_fallback(words: list[Word]) -> list[list[Word]]:
    """Pure-stdlib sentence split on terminal punctuation with abb, guards."""

    sentences: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        current.append(word)
        if _is_sentence_end(word.text):
            sentences.append(current)
            current = []
    if current:  # trailing words without a closing terminal
        sentences.append(current)
    return sentences


def split_sentences(words: list[Word], config: SegmenterConfig) -> list[list[Word]]:
    """HARD sentence cut: group words into sentences (pysbd or stdlib fallback)."""

    if not words:
        return []

    if config.use_external_segmenter:
        # Build a normalized string plus per-token char spans for alignment.
        token_spans: list[tuple[int, int]] = []
        parts: list[str] = []
        pos = 0
        for i, word in enumerate(words):
            tok = word.text.strip()
            if i > 0:
                parts.append(" ")
                pos += 1
            start = pos
            parts.append(tok)
            pos += len(tok)
            token_spans.append((start, pos))
        text = "".join(parts)

        bounds = _external_sentence_bounds(text)
        if bounds:
            return _split_sentences_external(words, bounds, token_spans)

    return _split_sentences_fallback(words)


# --- Step 4: per-sentence duration normalization -----------------------------


def _best_split_index(words: list[Word], config: SegmenterConfig) -> int | None:
    """Return the best within-sentence split index ``k``, or None if unsplittable.

    Only splits where BOTH resulting parts are >= ``min_s`` are eligible (we never
    create a sub-min fragment). Among eligible splits we rank by tier:

        tier 2 — a real PAUSE (gap >= pause_threshold_s): the narrator is breathing
        tier 1 — a CLAUSE boundary (comma/semicolon/colon, or a leading conjunction)
        tier 0 — neither; fall back to pure balance

    Within a tier we prefer the split that best **balances** both sub-beats near
    ``target_s`` (minimize squared deviation), tie-broken by the larger pause gap.
    """

    n = len(words)
    if n < 2:
        return None

    target = config.target_s
    candidates: list[tuple[int, float, float, int]] = []  # (tier, balance, neg_gap, k)
    for k in range(1, n):
        left, right = words[:k], words[k:]
        ld, rd = _duration(left), _duration(right)
        if ld < config.min_s or rd < config.min_s:
            continue  # never create a sub-min fragment

        gap = words[k].start - words[k - 1].end
        is_pause = gap >= config.pause_threshold_s

        prev_tok = words[k - 1].text.strip().rstrip(_TRAILING)
        next_tok = words[k].text.strip().lstrip(_LEADING).lower().rstrip(",.!?;:")
        is_clause = prev_tok.endswith(_CLAUSE_TERMINALS) or next_tok in _CONJUNCTIONS

        tier = 2 if is_pause else (1 if is_clause else 0)
        balance = (ld - target) ** 2 + (rd - target) ** 2
        # Sort key wants: highest tier, lowest balance, largest gap.
        candidates.append((-tier, balance, -gap, k))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]


def normalize_sentence(words: list[Word], config: SegmenterConfig) -> list[list[Word]]:
    """Split ONE sentence into beats within ``[min_s, max_s]`` (never sub-min).

    A sentence at or under ``max_s`` becomes a single beat (possibly sub-min — the
    merge step handles that). An over-max sentence is recursively split at its best
    internal break; if no split avoids a sub-min fragment, the sentence is left as a
    single slightly-over-max beat rather than butchered.
    """

    if _duration(words) <= config.max_s or len(words) < 2:
        return [words]
    k = _best_split_index(words, config)
    if k is None:
        return [words]  # unsplittable without violating min_s
    return normalize_sentence(words[:k], config) + normalize_sentence(words[k:], config)


# --- Step 5: merge short beats ----------------------------------------------


def merge_short_beats(
    beats: list[list[Word]], config: SegmenterConfig
) -> list[list[Word]]:
    """Fold sub-``min_s`` beats into the neighbor closest to ``target_s``.

    This is the ONLY step allowed to cross a sentence boundary, and only because a
    whole sub-min sentence (e.g. "Fast.") cannot stand on its own. Two beats that
    are already in range are NEVER merged just to approach the target.
    """

    merged: list[list[Word]] = [list(b) for b in beats]
    if len(merged) <= 1:
        return merged

    changed = True
    while changed and len(merged) > 1:
        changed = False
        for i, beat in enumerate(merged):
            if _duration(beat) >= config.min_s:
                continue

            prev_i = i - 1 if i > 0 else None
            next_i = i + 1 if i < len(merged) - 1 else None
            if prev_i is None and next_i is None:
                break

            # Pick the neighbor whose merged duration lands closest to target.
            options: list[tuple[float, int]] = []
            if prev_i is not None:
                options.append((abs(_duration(merged[prev_i] + beat) - config.target_s), prev_i))
            if next_i is not None:
                options.append((abs(_duration(beat + merged[next_i]) - config.target_s), next_i))
            options.sort()
            target_i = options[0][1]

            if target_i < i:
                merged[target_i] = merged[target_i] + beat
            else:
                merged[target_i] = beat + merged[target_i]
            del merged[i]
            changed = True
            break
    return merged


# --- Orchestration -----------------------------------------------------------


def segment(words: list[Word], config: SegmenterConfig | None = None) -> list[Beat]:
    """Convert a flat word stream into ordered, sentence-clean visual beats."""

    config = config or SegmenterConfig()
    words = transcript_normalize(words, config)
    if not words:
        return []

    candidate_beats: list[list[Word]] = []
    for sentence in split_sentences(words, config):  # step 3: HARD cuts first
        candidate_beats.extend(normalize_sentence(sentence, config))  # step 4

    normalized = merge_short_beats(candidate_beats, config)  # step 5

    beats: list[Beat] = []
    for index, beat_words in enumerate(normalized):  # step 6: recompute + reindex
        if not beat_words:
            continue
        beats.append(
            Beat(
                index=index,
                text=_beat_text(beat_words),
                start_s=float(beat_words[0].start),
                end_s=float(beat_words[-1].end),
                words=beat_words,
            )
        )
    return beats


# --- Dev helper --------------------------------------------------------------


def report(beats: list[Beat], config: SegmenterConfig | None = None) -> None:
    """Print a debug table (#, start, end, dur, text) with flags and a footer."""

    config = config or SegmenterConfig()
    print(f"\n{len(beats)} beats")
    print("-" * 78)
    print(f"{'#':>3}  {'start':>7}  {'end':>7}  {'dur':>5}  text")
    print("-" * 78)
    for beat in beats:
        dur = beat.end_s - beat.start_s
        flag = "  <min" if dur < config.min_s else ("  >max" if dur > config.max_s else "")
        print(f"{beat.index:>3}  {beat.start_s:>7.2f}  {beat.end_s:>7.2f}  {dur:>5.2f}  {beat.text}{flag}")
    print("-" * 78)
    if beats:
        durations = [b.end_s - b.start_s for b in beats]
        print(
            f"avg={sum(durations) / len(durations):.2f}s  "
            f"min={min(durations):.2f}s  max={max(durations):.2f}s  n={len(beats)}"
        )


def sentence_id_map(words: list[Word], config: SegmenterConfig | None = None) -> dict[int, int]:
    """Map ``id(word)`` -> sentence index (test/debug helper for invariants)."""

    config = config or SegmenterConfig()
    mapping: dict[int, int] = {}
    for si, sentence in enumerate(split_sentences(words, config)):
        for word in sentence:
            mapping[id(word)] = si
    return mapping
