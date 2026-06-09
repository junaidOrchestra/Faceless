"""Async SQLAlchemy engine, session factory, and ORM base.

Uses SQLAlchemy 2.x with the async ``psycopg`` (psycopg3) driver. The engine is
created lazily and cached so the same pool is shared across the app and the
background worker. All queries go through the ORM / parameterized statements —
never string interpolation.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models in this service."""


def _resolve_ipv4(host: str) -> str | None:
    """Return the first IPv4 address for ``host``, or ``None`` if there is none.

    Used to pin the connection to IPv4 on platforms without an IPv6 route (e.g.
    Hugging Face Spaces) talking to dual-stack providers (e.g. Neon) whose
    hostname resolves to both A and AAAA records — the resolver may prefer the
    unreachable IPv6 address. An IP literal or IPv6-only host returns ``None`` so
    the caller falls back to the normal resolver.
    """

    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_INET)
    except OSError:
        return None
    for info in infos:
        addr = info[4][0]
        if addr:
            return addr
    return None


def _is_neon_pooler_host(host: str | None) -> bool:
    """Return true for Neon pooled endpoints that reject startup ``options``."""

    h = (host or "").lower()
    return "neon.tech" in h and ("pooler" in h or ".c-" in h)


def _connect_args(settings: Settings) -> dict:
    """libpq connect args: per-connection timeouts plus optional IPv4 pinning.

    For normal Postgres/direct connections, ``options`` is set via the startup
    packet to apply statement_timeout/lock_timeout per connection.

    Neon pooled endpoints reject these startup parameters with:
    "unsupported startup parameter in options: statement_timeout". For those
    hosts we deliberately skip startup options so the connection succeeds.

    When ``db_force_ipv4`` is on, the database host is resolved to an IPv4 address
    passed as libpq ``hostaddr`` while ``host`` (from the URL) is kept for TLS
    SNI / certificate verification, so ``sslmode=require`` still works.
    """

    args: dict[str, str] = {}

    try:
        host = make_url(settings.database_url).host
    except Exception:  # noqa: BLE001 - never block engine creation on URL parsing
        host = None

    if _is_neon_pooler_host(host):
        logger.info(
            "skipping DB startup timeout options for Neon pooler host %s "
            "(pooler rejects statement_timeout/lock_timeout startup parameters)",
            host,
        )
    else:
        opts: list[str] = []
        if settings.db_statement_timeout_s and settings.db_statement_timeout_s > 0:
            opts.append(f"-c statement_timeout={int(settings.db_statement_timeout_s * 1000)}")
        if settings.db_lock_timeout_s and settings.db_lock_timeout_s > 0:
            opts.append(f"-c lock_timeout={int(settings.db_lock_timeout_s * 1000)}")
        if opts:
            args["options"] = " ".join(opts)

    if settings.db_force_ipv4 and host:
        ipv4 = _resolve_ipv4(host)
        if ipv4:
            # libpq: host kept for SNI/cert, hostaddr forces the IPv4 socket.
            args["hostaddr"] = ipv4
            logger.info("pinning DB connection to IPv4 %s for host %s", ipv4, host)
        else:
            logger.warning(
                "db_force_ipv4 is on but no IPv4 address found for host %r; "
                "using the default resolver",
                host,
            )

    return args


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (created on first use)."""

    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,  # transparently recycle connections dropped by the host
        future=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=int(settings.db_pool_recycle_s),
        connect_args=_connect_args(settings),
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
