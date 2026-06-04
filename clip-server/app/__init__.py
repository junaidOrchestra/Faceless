"""CLIP server — a beat-agnostic "keywords -> ranked assets" primitive.

This package exposes a FastAPI application that, given a batch of keywords,
searches configurable stock sources, embeds the previews with CLIP, ranks them by
cosine similarity, and returns assets. It is deliberately ignorant of audio,
beats, videos, or rendering: it is a generic media-finding service.
"""

__version__ = "0.1.0"
