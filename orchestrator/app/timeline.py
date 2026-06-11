"""Gapless timeline math shared by render and billing.

This module is also responsible for the "tighten audio" math: removing dead air
(silences/pauses) and filler words ("um", "uh", …) from the kept beats. All of
it is expressed as pure functions over ``(start, end)`` spans so it can be unit
tested and reused by both the renderer and the billing/tier-limit checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# When "remove silences" is on we SHORTEN long pauses rather than deleting them:
# a short breath is kept after each pause so consecutive sentences/beats don't
# run together (e.g. "…morning," and "there…" need a beat between them). Pauses
# shorter than the detector's threshold are never touched, so natural micro-gaps
# are always preserved.
MIN_SILENCE_KEEP_S = 0.3


@dataclass(frozen=True, slots=True)
class BeatTiming:
    index: int
    start_s: float
    end_s: float
    # "narration" = backed by the narration window [start_s, end_s]. "insert" = a
    # user-added standalone animated text card with no narration: it occupies
    # ``duration_s`` of the timeline and an equal silent gap in the audio track.
    kind: str = "narration"
    duration_s: float = 0.0


@dataclass(slots=True)
class AudioPiece:
    """One ordered slice of the assembled narration track.

    * ``kind == "narration"`` — keep ``[start_s, end_s]`` of the source narration.
    * ``kind == "silence"`` — insert ``duration_s`` seconds of silence (used where
      a standalone inserted beat sits, so audio length keeps matching video).
    """

    kind: str
    start_s: float = 0.0
    end_s: float = 0.0
    duration_s: float = 0.0


@dataclass(frozen=True, slots=True)
class WordTiming:
    """One transcribed word with timing and a filler flag."""

    start_s: float
    end_s: float
    is_filler: bool = False


@dataclass(slots=True)
class RenderPlan:
    """The result of resolving a selection into concrete cut windows.

    * ``windows`` — flattened ``(start, end)`` slices of the narration to keep,
      in render order. One visual segment may map to several windows once inner
      silences/fillers are cut out.
    * ``beat_durations`` — ``(beat_index, clip_duration_s)`` for each kept beat,
      in order. The clip's on-screen duration equals the sum of its windows.
    * ``total_s`` — total kept duration (== sum of every window).
    """

    windows: list[tuple[float, float]] = field(default_factory=list)
    beat_durations: list[tuple[int, float]] = field(default_factory=list)
    total_s: float = 0.0
    # Ordered audio assembly including silence inserts for standalone beats. When
    # there are no inserts this is just the narration windows in order, so the
    # renderer can use either ``windows`` (legacy) or ``audio_pieces``.
    audio_pieces: list[AudioPiece] = field(default_factory=list)
    # True when any kept beat is a standalone insert, so the renderer must always
    # re-assemble the audio track (to splice in the silent gaps) even with no
    # exclusions/tighten options.
    has_inserts: bool = False


def clip_boundaries(
    segments: list[BeatTiming], audio_duration_s: float | None
) -> list[float]:
    """Return ``len(segments)+1`` monotonic boundaries covering ``[0, audio_end]``.

    The renderer concatenates clips back-to-back, so a clip's *duration* is what
    decides how long an image stays on screen. To keep visuals in sync with the
    narration and make the rendered length equal the audio length, the timeline
    is GAPLESS: each image shows from its own beat's start until the NEXT beat
    begins (absorbing inter-beat silence), and the last clip runs to the end of
    the audio (covering lead-out silence).
    """

    if not segments:
        return [0.0, audio_duration_s or 3.0]

    boundaries: list[float] = [0.0]
    for seg in segments[1:]:
        boundaries.append(float(seg.start_s))

    last_end = audio_duration_s if audio_duration_s else segments[-1].end_s
    boundaries.append(max(float(last_end), float(segments[-1].end_s)))

    for i in range(1, len(boundaries)):
        if boundaries[i] < boundaries[i - 1]:
            boundaries[i] = boundaries[i - 1]
    return boundaries


def subtract_spans(
    base: list[tuple[float, float]], cuts: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Remove every ``cut`` interval from the ``base`` intervals.

    Both lists are ``(start, end)`` in seconds. Returns the remaining pieces in
    order, dropping any zero/negative-length fragments. Cuts may overlap and need
    not be sorted.
    """

    if not cuts:
        return [(s, e) for s, e in base if e > s]

    merged = _merge(cuts)
    out: list[tuple[float, float]] = []
    for seg_start, seg_end in base:
        cursor = seg_start
        for cut_start, cut_end in merged:
            if cut_end <= cursor or cut_start >= seg_end:
                continue  # cut is entirely outside this segment
            if cut_start > cursor:
                out.append((cursor, min(cut_start, seg_end)))
            cursor = max(cursor, cut_end)
            if cursor >= seg_end:
                break
        if cursor < seg_end:
            out.append((cursor, seg_end))
    return [(s, e) for s, e in out if e > s]


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sort and union overlapping/adjacent ``(start, end)`` spans."""

    cleaned = sorted((min(s, e), max(s, e)) for s, e in spans)
    merged: list[tuple[float, float]] = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def beat_kept_spans(
    *,
    beat: BeatTiming,
    boundary_start: float,
    boundary_end: float,
    words: list[WordTiming] | None,
    silence_spans: list[tuple[float, float]] | None,
    remove_silence: bool,
    remove_fillers: bool,
    min_silence_keep_s: float = MIN_SILENCE_KEEP_S,
) -> list[tuple[float, float]]:
    """Resolve one kept beat into the narration windows to actually play.

    The base is always the GAPLESS boundary window
    ``[boundary_start, boundary_end]`` (it spans this beat's start to the next
    beat's start, so inter-beat silence belongs to this beat's window).

    ``remove_silence`` SHORTENS each detected pause inside the window down to
    ``min_silence_keep_s`` rather than deleting it — a short breath is kept after
    each pause so words/sentences never run together. ``remove_fillers``
    subtracts each filler word's ``[start, end]`` entirely. The result is clamped
    to be non-empty: a beat that would vanish keeps a short sliver so its visual
    still appears.
    """

    base = [(float(boundary_start), float(boundary_end))]

    cuts: list[tuple[float, float]] = []
    if remove_silence and silence_spans:
        for span_start, span_end in silence_spans:
            # Keep the first ``min_silence_keep_s`` of each pause; cut the excess.
            cut_start = span_start + min_silence_keep_s
            if span_end > cut_start:
                cuts.append((cut_start, span_end))
    if remove_fillers and words:
        cuts.extend((w.start_s, w.end_s) for w in words if w.is_filler)

    spans = subtract_spans(base, cuts) if cuts else [(s, e) for s, e in base if e > s]
    if not spans:
        # Everything was cut (e.g. a beat that is only a filler word). Keep a tiny
        # window so the beat's visual still renders rather than disappearing.
        start = float(beat.start_s)
        spans = [(start, start + 0.05)]
    return spans


def build_render_plan(
    segments: list[BeatTiming],
    audio_duration_s: float | None,
    excluded: set[int],
    *,
    words_by_index: dict[int, list[WordTiming]] | None = None,
    silence_spans: list[tuple[float, float]] | None = None,
    remove_silence: bool = False,
    remove_fillers: bool = False,
    min_silence_keep_s: float = MIN_SILENCE_KEEP_S,
) -> RenderPlan:
    """Resolve a selection (+ tighten-audio options) into a concrete RenderPlan."""

    plan = RenderPlan()
    if not segments:
        return plan
    words_by_index = words_by_index or {}

    # Narration boundaries are computed over NARRATION beats only; standalone
    # inserts don't define narration windows. We walk the full ordered list and
    # advance a pointer into the narration sublist as we pass each narration beat.
    narration = [s for s in segments if (s.kind or "narration") != "insert"]
    boundaries = clip_boundaries(narration, audio_duration_s) if narration else [0.0, 0.0]
    nar_pos = 0
    for seg in segments:
        if (seg.kind or "narration") == "insert":
            if seg.index in excluded:
                continue
            # A standalone card: its on-screen length is duration_s and it splices
            # an equal silent gap into the audio (its SFX is mixed on top later).
            duration = max(0.2, float(seg.duration_s or 0.0))
            plan.audio_pieces.append(AudioPiece(kind="silence", duration_s=duration))
            plan.beat_durations.append((seg.index, duration))
            plan.total_s += duration
            plan.has_inserts = True
            continue

        i = nar_pos
        nar_pos += 1
        if seg.index in excluded:
            continue
        spans = beat_kept_spans(
            beat=seg,
            boundary_start=boundaries[i],
            boundary_end=boundaries[i + 1],
            words=words_by_index.get(seg.index),
            silence_spans=silence_spans,
            remove_silence=remove_silence,
            remove_fillers=remove_fillers,
            min_silence_keep_s=min_silence_keep_s,
        )
        duration = sum(e - s for s, e in spans)
        plan.windows.extend(spans)
        plan.audio_pieces.extend(AudioPiece(kind="narration", start_s=s, end_s=e) for s, e in spans)
        plan.beat_durations.append((seg.index, duration))
        plan.total_s += duration
    return plan


def render_duration_seconds(
    segments: list[BeatTiming],
    audio_duration_s: float | None,
    excluded: set[int],
    *,
    words_by_index: dict[int, list[WordTiming]] | None = None,
    silence_spans: list[tuple[float, float]] | None = None,
    remove_silence: bool = False,
    remove_fillers: bool = False,
    min_silence_keep_s: float = MIN_SILENCE_KEEP_S,
) -> float:
    """Total kept duration (for tier limits and credits), honouring trims.

    With no trims this equals the gapless sum of kept-beat windows (the full
    narration length when nothing is excluded).
    """

    return build_render_plan(
        segments,
        audio_duration_s,
        excluded,
        words_by_index=words_by_index,
        silence_spans=silence_spans,
        remove_silence=remove_silence,
        remove_fillers=remove_fillers,
        min_silence_keep_s=min_silence_keep_s,
    ).total_s
