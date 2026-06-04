"""Orchestrator Postgres models — video jobs, beats, assignments."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clip_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Beat(Base):
    __tablename__ = "beats"

    video_job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    queries: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class BeatAssignment(Base):
    __tablename__ = "beat_assignments"

    video_job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    beat_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str | None] = mapped_column(String(64))
    media_url: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[float | None] = mapped_column(Float)
    attribution: Mapped[str | None] = mapped_column(Text)
