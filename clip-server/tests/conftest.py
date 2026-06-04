"""Pytest fixtures — test app with a deterministic stub embedder (no torch download)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import get_settings
from app.db import get_sessionmaker
from app.embedding.base import Embedder
from app.main import app
from app.models import Asset, Job
from app.worker import JobWorker


class StubEmbedder(Embedder):
    """Deterministic 512-d vectors for tests — no sentence-transformers load."""

    def _vec(self, seed: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(seed)) % (2**32))
        v = rng.standard_normal(512).astype(np.float32)
        v /= np.linalg.norm(v) + 1e-8
        return v

    def embed_images(self, images: list[bytes]) -> np.ndarray:
        return np.stack([self._vec(f"img-{len(b)}-{b[:8]!r}") for b in images])

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(f"txt-{t}") for t in texts])


@pytest.fixture(scope="session", autouse=True)
def _env_defaults() -> None:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://faceless:faceless@localhost:5432/clip",
    )
    os.environ.setdefault("API_AUTH_SECRET", "test-secret")
    os.environ.setdefault("ENABLED_SOURCES", '["stub"]')
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """ASGI client with in-process worker and stub CLIP."""

    settings = get_settings()
    embedder = StubEmbedder()
    app.state.embedder = embedder
    worker = JobWorker(settings, embedder)
    await worker.start()

    # Clean job/asset tables between tests.
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(Job))
        await session.execute(delete(Asset))
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    await worker.stop()
    get_settings.cache_clear()
