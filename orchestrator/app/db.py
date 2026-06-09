"""Async SQLAlchemy setup for the orchestrator database.

The ONLY relational database this app connects to is the one in ``DATABASE_URL``
— this must be **Neon** (our Postgres for users/projects/credits/video jobs).
Supabase is used for **authentication only** (JWT verification in
``app.identity``) and is never opened as a SQL connection here. The
:func:`safe_db_target` helper logs which host we're hitting (without credentials)
so a misconfigured ``DATABASE_URL`` (e.g. pointed at Supabase) is obvious.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


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


def safe_db_target(database_url: str | None = None) -> str:
    """Return a credential-free 'host:port/dbname' description of the DB target.

    Used for logging so we can see which database the app is talking to (and spot
    a wrong ``DATABASE_URL``, e.g. a Supabase host instead of Neon) without ever
    leaking the username or password.
    """

    url_str = database_url or get_settings().database_url
    try:
        url = make_url(url_str)
    except Exception:  # noqa: BLE001 - never fail logging on a malformed URL
        return "<unparseable DATABASE_URL>"

    host = url.host or "<no-host>"
    port = url.port or 5432
    database = url.database or "<no-db>"
    provider = _provider_hint(host)
    return f"{host}:{port}/{database} (provider={provider})"


def _provider_hint(host: str) -> str:
    """Best-effort guess of the DB provider from its hostname (for logs only)."""

    h = (host or "").lower()
    if "neon.tech" in h:
        return "neon"
    if "supabase" in h:
        return "supabase"  # likely a misconfiguration — app DB should be Neon
    if h in {"db", "localhost", "127.0.0.1"}:
        return "local"
    return "unknown"


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
    SNI / certificate verification, so ``sslmode=require`` still works. This is
    needed on IPv6-less hosts (e.g. HF Spaces) talking to dual-stack Neon.
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

    if settings.db_force_ipv4:
        if host:
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
    settings = get_settings()
    target = safe_db_target(settings.database_url)
    logger.info("connecting to Postgres (DATABASE_URL) -> %s", target)
    if "provider=supabase" in target:
        logger.warning(
            "DATABASE_URL points at a Supabase host (%s). Supabase is for AUTH "
            "ONLY; app data (users/projects/credits) must use Neon. Set "
            "DATABASE_URL to your Neon connection string.",
            target,
        )
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=int(settings.db_pool_recycle_s),
        connect_args=_connect_args(settings),
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
