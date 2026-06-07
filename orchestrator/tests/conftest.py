"""Orchestrator test fixtures — all external deps stubbed."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import get_settings
from app.db import get_sessionmaker
from app.main import app
from app.models import Beat, BeatAssignment, VideoJob

@pytest.fixture(scope="session", autouse=True)
def _env() -> None:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://faceless:faceless@localhost:5432/orchestrator",
    )
    os.environ.setdefault("API_AUTH_SECRET", "test-secret")
    os.environ.setdefault("CLIP_SERVER_SECRET", "unused")
    os.environ.setdefault("LLM_PROVIDER", "stub")
    os.environ.setdefault("USE_STUB_CLIP", "1")
    os.environ.setdefault("USE_STUB_RENDERER", "1")
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(BeatAssignment))
        await session.execute(delete(Beat))
        await session.execute(delete(VideoJob))
        await session.commit()

    # Drive the app lifespan explicitly so the staged worker pools + clip poller
    # start (httpx>=0.28 ASGITransport no longer manages lifespan itself).
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http

    get_settings.cache_clear()
