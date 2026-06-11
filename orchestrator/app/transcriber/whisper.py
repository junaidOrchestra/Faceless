"""faster-whisper transcriber with sentence-clean, rule-based beat segmentation.

We deliberately do **not** use Whisper's own segment boundaries (they are tuned
for subtitles and are often uneven, mid-sentence fragments). Instead we collect
the **word-level timestamps** and re-chunk them into evenly paced visual beats via
:mod:`app.transcriber.segmenter`, where sentence boundaries are hard cuts.
"""

from __future__ import annotations

import asyncio
import logging

from .base import BeatSegment, Transcriber, WordSpan
from .fillers import is_filler
from .segmenter import Beat, SegmenterConfig, Word, segment

logger = logging.getLogger(__name__)


class WhisperTranscriber(Transcriber):
    """Transcribe audio and emit beats normalized for on-screen pacing."""

    def __init__(
        self,
        config: SegmenterConfig,
        model_size: str = "base",
        device: str = "cpu",
    ) -> None:
        from faster_whisper import WhisperModel

        self._config = config
        self._model = WhisperModel(model_size, device=device, compute_type="int8")

    async def transcribe(self, audio_path: str) -> list[BeatSegment]:
        # faster-whisper is sync; run in a thread so we do not block the event loop.
        beats = await asyncio.to_thread(self.beats_from_audio, audio_path)
        return [
            BeatSegment(
                b.index,
                b.text,
                b.start_s,
                b.end_s,
                words=[
                    WordSpan(
                        text=w.text,
                        start_s=float(w.start),
                        end_s=float(w.end),
                        is_filler=is_filler(w.text),
                    )
                    for w in b.words
                ],
            )
            for b in beats
        ]

    def beats_from_audio(self, audio_path: str) -> list[Beat]:
        """Synchronous helper returning rich :class:`Beat` objects (for debugging)."""

        words = self._extract_words(audio_path)
        beats = segment(words, self._config)
        logger.info("transcribed %s words into %s visual beats", len(words), len(beats))
        return beats

    def _extract_words(self, audio_path: str) -> list[Word]:
        """Flatten every Whisper word across all segments into one timeline."""

        segments, _info = self._model.transcribe(audio_path, word_timestamps=True)
        words: list[Word] = []
        for seg in segments:
            seg_words = list(seg.words or [])
            if seg_words:
                words.extend(
                    Word(text=w.word, start=float(w.start), end=float(w.end))
                    for w in seg_words
                )
            elif seg.text.strip():
                # Fallback when word timings are missing: treat the whole segment
                # as one pseudo-word so it still participates in segmentation.
                words.append(Word(text=seg.text, start=float(seg.start), end=float(seg.end)))
        return words
