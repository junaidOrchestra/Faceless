from __future__ import annotations

import os

from ..config import Settings
from .base import ClipClient
from .http import HttpClipClient
from .stub import StubClipClient


def build_clip_client(settings: Settings) -> ClipClient:
    if os.environ.get("USE_STUB_CLIP") == "1":
        return StubClipClient()
    return HttpClipClient(settings.clip_server_url, settings.clip_server_secret)
