"""Build the configured transcriber."""

from __future__ import annotations

import os

from ..config import Settings
from .base import Transcriber
from .segmenter import SegmenterConfig
from .stub import StubTranscriber
from .whisper import WhisperTranscriber


def build_segmenter_config(settings: Settings) -> SegmenterConfig:
    """Map env-backed settings onto the segmenter's config dataclass."""

    return SegmenterConfig(
        target_s=settings.beat_target_duration_s,
        min_s=settings.beat_min_duration_s,
        max_s=settings.beat_max_duration_s,
        pause_threshold_s=settings.beat_pause_threshold_s,
        normalize_transcript=settings.beat_normalize_transcript,
        use_external_segmenter=settings.beat_use_external_segmenter,
    )


def build_transcriber(settings: Settings, *, force_stub: bool = False) -> Transcriber:
    if force_stub or os.environ.get("USE_STUB_TRANSCRIBER") == "1":
        return StubTranscriber()
    return WhisperTranscriber(
        build_segmenter_config(settings),
        model_size=settings.whisper_model_size,
    )
