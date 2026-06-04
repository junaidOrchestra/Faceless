"""Abstract embedder interface.

The concrete CLIP implementation can later be swapped for a remote inference
server without changing the ranking pipeline — only this ABC's contract matters
to callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    """Embed images and text into a shared vector space for cosine ranking."""

    @abstractmethod
    def embed_images(self, images: list[bytes]) -> np.ndarray:
        """Return an ``(N, D)`` float32 array of image embeddings."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Return an ``(N, D)`` float32 array of text embeddings."""
