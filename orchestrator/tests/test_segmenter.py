"""Tests for the visual-beat segmenter: invariants + cross-boundary regression.

These are pure-function tests (no model, no DB, no network). They build a
synthetic word stream with realistic timings from a transcript, then assert the
structural and pacing invariants the segmenter must guarantee.
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.transcriber.segmenter import (
    SegmenterConfig,
    Word,
    _best_split_index,
    _is_sentence_end,
    sentence_id_map,
    segment,
    split_sentences,
)

CONFIG = SegmenterConfig(target_s=3.5, min_s=1.5, max_s=5.0, pause_threshold_s=0.35)
EPS = 1e-6

# India–Israel sample. Includes the known cross-boundary trap ("...movement."
# immediately followed by "Public alignment...") and a pair of very short
# sentences ("Israel delivered. Fast.") that must merge rather than flash.
INDIA_ISRAEL_TEXT = (
    "India and Israel share a deep strategic partnership. "
    "Over the years, the relationship has grown across defense, technology, and trade. "
    "Publicly, both nations express strong alignment. "
    "Privately, the cooperation runs even deeper. "
    "When tensions rose in the region, Israel delivered. "
    "Fast. "
    "This reflects a broader movement. "
    "Public alignment often hides private complexity."
)


def build_words(
    text: str,
    *,
    word_dur: float = 0.42,
    word_gap: float = 0.06,
    sentence_pause: float = 0.55,
) -> list[Word]:
    """Synthesize word timestamps from text.

    A small inter-word gap is used within sentences, and a larger pause after a
    sentence-ending token, mimicking how a narrator actually speaks.
    """

    tokens = text.split()
    words: list[Word] = []
    t = 0.0
    for i, tok in enumerate(tokens):
        start = t
        end = t + word_dur
        # Whisper-style leading space on every token but the first.
        words.append(Word(text=(" " + tok) if i > 0 else tok, start=start, end=end))
        t = end
        t += sentence_pause if _is_sentence_end(tok) else word_gap
    return words


@pytest.fixture
def words() -> list[Word]:
    return build_words(INDIA_ISRAEL_TEXT)


@pytest.fixture
def beats(words: list[Word]):
    return segment(words, CONFIG)


# --- Sentence-end helper -----------------------------------------------------


def test_is_sentence_end_guards() -> None:
    assert _is_sentence_end("partnership.")
    assert _is_sentence_end("really?")
    assert _is_sentence_end("now!")
    assert _is_sentence_end('movement."')  # trailing quote
    # Guards: abbreviations, initials, enumerations are NOT sentence ends.
    assert not _is_sentence_end("U.S.")
    assert not _is_sentence_end("Dr.")
    assert not _is_sentence_end("e.g.")
    assert not _is_sentence_end("A.")
    assert not _is_sentence_end("1.")
    assert not _is_sentence_end("trade")


# --- KEY invariant: no beat mixes a partial sentence with other content ------


def test_no_beat_spans_partial_sentence(words, beats) -> None:
    """A beat may hold part of ONE sentence, or several WHOLE sentences — never a
    full sentence plus a partial next one (the structural bug being fixed)."""

    sent_of = sentence_id_map(words, CONFIG)
    sent_sizes = Counter(sent_of.values())

    for beat in beats:
        counts = Counter(sent_of[id(w)] for w in beat.words)
        if len(counts) > 1:
            # Multi-sentence beat is only allowed if every sentence is WHOLE.
            for sid, c in counts.items():
                assert c == sent_sizes[sid], (
                    f"beat {beat.index} contains a partial sentence {sid}: {beat.text!r}"
                )


def test_no_internal_sentence_terminal_in_partial_beats(words, beats) -> None:
    """If a beat holds only part of one sentence, it cannot contain a terminal."""

    sent_of = sentence_id_map(words, CONFIG)
    sent_sizes = Counter(sent_of.values())
    for beat in beats:
        counts = Counter(sent_of[id(w)] for w in beat.words)
        is_partial_single = len(counts) == 1 and next(iter(counts.values())) < sent_sizes[
            next(iter(counts))
        ]
        if is_partial_single:
            # No interior sentence-ending word (last word may legitimately end one).
            for w in beat.words[:-1]:
                assert not _is_sentence_end(w.text), f"interior terminal in {beat.text!r}"


# --- REGRESSION: the specific cross-boundary case ----------------------------


def test_regression_movement_public_alignment_not_merged(beats) -> None:
    """No beat may contain BOTH the end of '...movement.' and 'Public alignment'."""

    for beat in beats:
        text = beat.text.lower()
        assert not ("movement." in text and "public alignment" in text), (
            f"cross-boundary beat resurfaced: {beat.text!r}"
        )


# --- Duration / structure invariants -----------------------------------------


def test_no_beat_below_min_after_merge(beats) -> None:
    assert len(beats) > 1
    for beat in beats:
        assert (beat.end_s - beat.start_s) >= CONFIG.min_s - EPS, (
            f"beat {beat.index} below min: {beat.text!r}"
        )


def test_short_sentence_is_merged_not_flashed(words, beats) -> None:
    """The sub-min sentence 'Fast.' must be absorbed into a neighbor, never alone.

    (It merges into whichever neighbor lands closest to target — here the following
    'This reflects a broader movement.' — which is allowed because 'Fast.' is a
    *whole* short sentence.)"""

    fast_beats = [b for b in beats if "fast." in b.text.lower()]
    assert len(fast_beats) == 1
    beat = fast_beats[0]
    # It must not be a lone "Fast." — i.e. it carries at least one more sentence.
    sent_of = sentence_id_map(words, CONFIG)
    sentences_in_beat = {sent_of[id(w)] for w in beat.words}
    assert len(sentences_in_beat) > 1, f"'Fast.' was left to flash alone: {beat.text!r}"
    assert (beat.end_s - beat.start_s) >= CONFIG.min_s


def test_over_max_only_when_unsplittable(words, beats) -> None:
    sent_of = sentence_id_map(words, CONFIG)
    for beat in beats:
        if (beat.end_s - beat.start_s) > CONFIG.max_s + EPS:
            counts = Counter(sent_of[id(w)] for w in beat.words)
            # Over-max is allowed for a merge of whole short sentences; for a
            # single-sentence beat it must be genuinely unsplittable.
            if len(counts) == 1:
                assert _best_split_index(beat.words, CONFIG) is None, (
                    f"over-max beat was splittable: {beat.text!r}"
                )


def test_beats_contiguous_ordered_indexed(beats) -> None:
    assert [b.index for b in beats] == list(range(len(beats)))
    for beat in beats:
        assert beat.start_s < beat.end_s
    for a, b in zip(beats, beats[1:]):
        assert a.end_s <= b.start_s + EPS, "beats overlap or are out of order"


def test_long_sentence_is_split(words, beats) -> None:
    """The long second sentence must be broken into multiple beats."""

    sentences = split_sentences(words, CONFIG)
    # Sentence index 1 is the long "Over the years, ..." sentence.
    long_sentence = sentences[1]
    duration = long_sentence[-1].end - long_sentence[0].start
    assert duration > CONFIG.max_s  # fixture sanity check

    # Count beats whose words belong to that sentence (by identity).
    long_word_ids = {id(w) for w in long_sentence}
    beats_touching_long = [b for b in beats if any(id(w) in long_word_ids for w in b.words)]
    assert len(beats_touching_long) >= 2, "long sentence should split into >= 2 beats"


# --- Fallback parity ---------------------------------------------------------


def test_stdlib_fallback_produces_valid_beats(words) -> None:
    cfg = SegmenterConfig(
        target_s=3.5, min_s=1.5, max_s=5.0, pause_threshold_s=0.35,
        use_external_segmenter=False,
    )
    beats = segment(words, cfg)
    assert len(beats) > 1
    sent_of = sentence_id_map(words, cfg)
    sent_sizes = Counter(sent_of.values())
    for beat in beats:
        counts = Counter(sent_of[id(w)] for w in beat.words)
        if len(counts) > 1:
            for sid, c in counts.items():
                assert c == sent_sizes[sid]
