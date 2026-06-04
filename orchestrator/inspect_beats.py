"""Debug utility: transcribe an audio file and print the visual beats.

Runs ONLY the transcription + rule-based beat segmentation — no database, no LLM,
no CLIP server, no rendering. Use it to eyeball how narration audio is chunked
into evenly paced, sentence-clean beats and to tune the BEAT_* thresholds.

Usage (inside the orchestrator Docker image, which has faster-whisper baked in):

    docker compose run --rm --no-deps \
        -v "C:/Code/AI/audios:/audio" \
        orchestrator \
        python inspect_beats.py /audio/narration.mp3

Or in any Python 3.11 venv with `pip install -r requirements-beats.txt`:

    python inspect_beats.py path/to/narration.mp3 --model base --max 5 --min 1.5
"""

from __future__ import annotations

import argparse

# Import directly (not via the factory) so we avoid pulling in Settings/DB config.
from app.transcriber.segmenter import SegmenterConfig, report
from app.transcriber.whisper import WhisperTranscriber


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect beat segmentation for an audio file.")
    parser.add_argument("audio", help="Path to the narration audio file (mp3/wav/m4a).")
    parser.add_argument("--model", default="base", help="faster-whisper model size.")
    parser.add_argument("--min", type=float, default=1.5, help="Min beat duration (s).")
    parser.add_argument("--target", type=float, default=3.5, help="Target beat duration (s).")
    parser.add_argument("--max", type=float, default=5.0, help="Max beat duration (s).")
    parser.add_argument("--pause", type=float, default=0.35, help="Pause threshold (s).")
    parser.add_argument(
        "--no-pysbd",
        action="store_true",
        help="Disable pysbd and use the stdlib sentence fallback.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = SegmenterConfig(
        target_s=args.target,
        min_s=args.min,
        max_s=args.max,
        pause_threshold_s=args.pause,
        use_external_segmenter=not args.no_pysbd,
    )
    transcriber = WhisperTranscriber(config, model_size=args.model)
    beats = transcriber.beats_from_audio(args.audio)

    print(f"\nsource: {args.audio}")
    report(beats, config)


if __name__ == "__main__":
    main()
