"""Async SQLAlchemy engine, session factory, and ORM base.

Uses SQLAlchemy 2.x with the async ``psycopg`` (psycopg3) driver. The engine is
created lazily and cached so the same pool is shared across the app and the
background worker. All queries go through the ORM / parameterized statements —
never string interpolation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models in this service."""


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (created on first use)."""

    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,  # transparently recycle connections dropped by the host
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the cached async session factory bound to the engine."""

    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session
