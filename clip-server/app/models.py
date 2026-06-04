"""Postgres ORM models for durable jobs and the asset embedding cache.

Jobs are the unit of work for the submit-poll API: they carry the client's input
as JSON, accumulate per-item results in ``items_result``, and track worker
ownership via ``claimed_at`` so stuck ``running`` jobs can be re-queued.

Assets are a long-lived cache keyed by ``(platform, external_id)``. When the
same stock item is requested again we reuse its stored CLIP embedding instead of
re-downloading and re-embedding the preview.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Job(Base):
    """A durable CLIP search job (submit-poll lifecycle)."""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    items_input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    items_result: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Asset(Base):
    """Cached stock asset with a CLIP embedding for reuse across jobs."""

    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_assets_platform_external"),)

    asset_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    media_url: Mapped[str] = mapped_column(Text, nullable=False)
    preview_url: Mapped[str] = mapped_column(Text, nullable=False)
    attribution_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attribution_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(512),  # clip-ViT-B-32
        nullable=False,
    )
    keyword: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
