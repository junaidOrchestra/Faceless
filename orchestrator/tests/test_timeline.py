from app.timeline import (
    BeatTiming,
    WordTiming,
    build_render_plan,
    clip_boundaries,
    render_duration_seconds,
    subtract_spans,
)


def test_clip_boundaries_gapless() -> None:
    segments = [
        BeatTiming(index=0, start_s=0.0, end_s=2.0),
        BeatTiming(index=1, start_s=3.0, end_s=5.0),
        BeatTiming(index=2, start_s=5.5, end_s=7.0),
    ]
    boundaries = clip_boundaries(segments, 10.0)
    assert boundaries == [0.0, 3.0, 5.5, 10.0]


def test_render_duration_excludes_beats() -> None:
    segments = [
        BeatTiming(index=0, start_s=0.0, end_s=2.0),
        BeatTiming(index=1, start_s=3.0, end_s=5.0),
        BeatTiming(index=2, start_s=5.5, end_s=7.0),
    ]
    full = render_duration_seconds(segments, 10.0, set())
    trimmed = render_duration_seconds(segments, 10.0, {1})
    assert full == 10.0
    assert trimmed == full - (5.5 - 3.0)


def test_subtract_spans_basic() -> None:
    # Cut a middle chunk and an overlapping chunk; fragments come back in order.
    assert subtract_spans([(0.0, 10.0)], [(2.0, 3.0), (5.0, 6.0)]) == [
        (0.0, 2.0),
        (3.0, 5.0),
        (6.0, 10.0),
    ]
    # Overlapping/unsorted cuts are merged.
    assert subtract_spans([(0.0, 10.0)], [(5.0, 7.0), (6.0, 8.0)]) == [
        (0.0, 5.0),
        (8.0, 10.0),
    ]
    # A cut covering the whole base removes it entirely.
    assert subtract_spans([(0.0, 5.0)], [(0.0, 5.0)]) == []


def test_remove_silence_shortens_pause_but_keeps_a_gap() -> None:
    # Two beats with a 1s inter-beat pause [2,3]. Removing silence SHORTENS the
    # pause to min_silence_keep_s rather than deleting it, so the sentences don't
    # run together.
    segments = [
        BeatTiming(index=0, start_s=0.0, end_s=2.0),
        BeatTiming(index=1, start_s=3.0, end_s=6.0),
    ]
    full = render_duration_seconds(segments, 6.0, set())
    tightened = render_duration_seconds(
        segments,
        6.0,
        set(),
        silence_spans=[(2.0, 3.0)],
        remove_silence=True,
        min_silence_keep_s=0.3,
    )
    assert full == 6.0
    # The 1s pause is cut to 0.3s: total = 6.0 - (1.0 - 0.3) = 5.3.
    assert abs(tightened - 5.3) < 1e-9


def test_remove_silence_no_spans_is_noop() -> None:
    # With no detected silence spans there is nothing to shorten.
    segments = [
        BeatTiming(index=0, start_s=0.0, end_s=2.0),
        BeatTiming(index=1, start_s=3.0, end_s=6.0),
    ]
    assert render_duration_seconds(segments, 6.0, set(), remove_silence=True) == 6.0


def test_remove_fillers_cuts_filler_words() -> None:
    segments = [BeatTiming(index=0, start_s=0.0, end_s=4.0)]
    words = {
        0: [
            WordTiming(0.0, 1.0, is_filler=False),
            WordTiming(1.0, 1.5, is_filler=True),  # "um"
            WordTiming(1.5, 4.0, is_filler=False),
        ]
    }
    plan = build_render_plan(
        segments, 4.0, set(), words_by_index=words, remove_fillers=True
    )
    assert plan.windows == [(0.0, 1.0), (1.5, 4.0)]
    assert plan.total_s == 3.5
    assert plan.beat_durations == [(0, 3.5)]
