"""Debug utility: classify beats into visual types (Phase 1 — inspect only).

Runs transcription + vocabulary + batched beat classification. No database,
CLIP server, or rendering. Use this to validate the visual_type classifier on
a script before wiring routing/rendering.

Usage (inside the orchestrator Docker image):

    docker compose run --rm --no-deps \\
        -v "C:/Code/AI/audios:/audio" \\
        orchestrator \\
        python inspect_classify.py /audio/narration.mp3

After a full job, inspect classifications stored in Postgres:

    docker compose exec -T db psql -U faceless -d orchestrator -P pager=off -c "
      SELECT b.index, left(b.text,50) AS text,
             b.queries->>'visual_type' AS type,
             b.queries->>'spec' AS spec,
             b.queries->>'overlay' AS overlay
      FROM beats b
      WHERE b.video_job_id = '<job-id>'
      ORDER BY b.index;
    "
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from app.config import get_settings
from app.llm.factory import build_llm
from app.transcriber.segmenter import SegmenterConfig
from app.transcriber.whisper import WhisperTranscriber


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify narration beats into visual types (inspect only)."
    )
    parser.add_argument("audio", help="Path to the narration audio file.")
    parser.add_argument("--model", default="base", help="faster-whisper model size.")
    parser.add_argument("--min", type=float, default=1.5, help="Min beat duration (s).")
    parser.add_argument("--target", type=float, default=3.5, help="Target beat duration (s).")
    parser.add_argument("--max", type=float, default=5.0, help="Max beat duration (s).")
    parser.add_argument("--pause", type=float, default=0.35, help="Pause threshold (s).")
    return parser.parse_args()


def _print_report(audio: str, beats: list, vocabulary, plans: list) -> None:
    print(f"\nsource: {audio}")
    print(f"TOPIC: {vocabulary.topic}")
    print(f"SUBJECTS: {', '.join(vocabulary.subjects) or '(none)'}")
    print(f"METAPHORS: {', '.join(vocabulary.metaphors) or '(none)'}")

    counts = Counter(p.visual_type for p in plans)
    print("\nTYPE DISTRIBUTION:")
    for visual_type, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"  {visual_type}: {count}")

    print(f"\n{'#':>3}  {'type':<11} {'dur':>5}  {'spec':<30}  {'overlay':<14}  text")
    print("-" * 115)
    for beat, plan in zip(beats, plans, strict=True):
        duration = beat.end_s - beat.start_s
        spec = (plan.spec or "")[:30]
        overlay = (plan.overlay or "")[:14]
        text = beat.text.replace("\n", " ")[:45]
        motion = "vid" if plan.prefers_video else "   "
        print(
            f"{beat.index:>3}  {plan.visual_type:<11} {duration:>4.1f}s {motion}  "
            f"{spec:<30}  {overlay:<14}  {text}"
        )


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    config = SegmenterConfig(
        target_s=args.target,
        min_s=args.min,
        max_s=args.max,
        pause_threshold_s=args.pause,
    )
    transcriber = WhisperTranscriber(config, model_size=args.model)
    llm = build_llm(settings)

    segments = await transcriber.transcribe(args.audio)
    beats_payload = [
        {"index": s.index, "text": s.text, "start_s": s.start_s, "end_s": s.end_s}
        for s in segments
    ]
    transcript = " ".join(s.text for s in segments)

    print("Deriving vocabulary...")
    vocabulary = await llm.vocabulary(transcript)
    print(f"Classifying {len(beats_payload)} beats...")
    plans = await llm.beat_queries(beats_payload, vocabulary)
    _print_report(args.audio, segments, vocabulary, plans)


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
