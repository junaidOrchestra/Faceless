"""CLIP embedder backed by sentence-transformers (loaded once at startup)."""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from .base import Embedder

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class ClipEmbedder(Embedder):
    """CLIP ViT-B/32 (or configured model) on CPU, loaded once per process."""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        # Import lazily so unit tests can stub the embedder without torch.
        from sentence_transformers import SentenceTransformer

        logger.info("Loading CLIP model %s on %s", model_name, device)
        self._model: SentenceTransformer = SentenceTransformer(model_name, device=device)
        logger.info("CLIP model ready.")

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        if not images:
            return np.zeros((0, 0), dtype=np.float32)
        pil_images = [Image.open(io.BytesIO(blob)).convert("RGB") for blob in images]
        vectors = self._model.encode(
            pil_images,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
