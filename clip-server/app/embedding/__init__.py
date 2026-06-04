"""Embedding backends for CLIP image/text vectors."""

from .base import Embedder
from .clip import ClipEmbedder

__all__ = ["ClipEmbedder", "Embedder"]
