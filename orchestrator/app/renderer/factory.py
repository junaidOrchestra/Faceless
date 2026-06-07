from __future__ import annotations

import os

from ..config import Settings
from .base import Renderer
from .ffmpeg import FFmpegRenderer
from .stub import StubRenderer


def build_renderer(settings: Settings) -> Renderer:
    if os.environ.get("USE_STUB_RENDERER") == "1":
        return StubRenderer()
    return FFmpegRenderer(
        settings.render_temp_dir,
        segment_concurrency=settings.render_segment_concurrency,
        threads=settings.render_threads,
        preset=settings.render_preset,
        crf=settings.render_crf,
    )
