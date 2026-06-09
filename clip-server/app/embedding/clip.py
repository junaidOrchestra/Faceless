"""CLIP embedder backed by sentence-transformers (loaded once at startup)."""

from __future__ import annotations

import io
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageFile

from .base import Embedder

# Stock CDNs occasionally return a 200 with a valid JPEG header but a truncated
# body. Letting PIL decode the partial data (instead of raising) keeps that
# preview usable rather than dropping the candidate outright.
ImageFile.LOAD_TRUNCATED_IMAGES = True

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ClipEmbedder(Embedder):
    """CLIP ViT-B/32 (or configured model) on CPU, loaded once per process."""

    def __init__(self, model_name: str, device: str = "cpu", *, text_cache_size: int = 512) -> None:
        # Import lazily so unit tests can stub the embedder without torch.
        from sentence_transformers import SentenceTransformer

        self._text_cache_size = max(0, text_cache_size)
        self._text_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        logger.info("Loading CLIP model %s on %s", model_name, device)
        self._model: SentenceTransformer = SentenceTransformer(model_name, device=device)
        logger.info("CLIP model ready.")

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        if not images:
            return np.zeros((0, 0), dtype=np.float32)
        pil_images: list[Image.Image] = []
        try:
            pil_images = [Image.open(io.BytesIO(blob)).convert("RGB") for blob in images]
            vectors = self._model.encode(
                pil_images,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return np.asarray(vectors, dtype=np.float32)
        finally:
            for image in pil_images:
                image.close()

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        if self._text_cache_size <= 0:
            vectors = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return np.asarray(vectors, dtype=np.float32)

        out: list[np.ndarray | None] = [None] * len(texts)
        misses: list[str] = []
        miss_positions: list[int] = []
        for i, text in enumerate(texts):
            cached = self._text_cache.get(text)
            if cached is not None:
                self._text_cache.move_to_end(text)
                out[i] = cached
            else:
                misses.append(text)
                miss_positions.append(i)

        if misses:
            vectors = np.asarray(
                self._model.encode(
                    misses,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
            for pos, text, vec in zip(miss_positions, misses, vectors, strict=True):
                self._text_cache[text] = vec
                self._text_cache.move_to_end(text)
                while len(self._text_cache) > self._text_cache_size:
                    self._text_cache.popitem(last=False)
                out[pos] = vec

        return np.stack([vec for vec in out if vec is not None]).astype(np.float32, copy=False)
