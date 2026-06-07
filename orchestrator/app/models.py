"""Orchestrator Postgres models — video jobs, beats, and per-beat assignments.

``VideoJob`` drives the job lifecycle and ``GET /videos/{id}``. ``Beat`` and
``BeatAssignment`` record the breakdown of a finished job (each spoken beat, its
timing/text, and the media clip selected for it) so ``GET /videos/{id}/beats``
can replay what the pipeline produced.
"""

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
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Beat(Base):
    """One spoken beat of a job: its transcript text, timing, and search queries."""

    __tablename__ = "beats"

    video_job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_s: Mapped[float] = mapped_column(Float, nullable=False)
    end_s: Mapped[float] = mapped_column(Float, nullable=False)
    queries: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class BeatAssignment(Base):
    """The media clip selected for a beat (or a text fallback when none matched).

    The scalar columns describe the *selected* clip that the renderer uses.
    ``candidates`` keeps the top ranked options for the beat (selected first,
    then alternates) so a UI can show choices and let the user swap; each entry
    carries both ``preview_url`` and ``media_url``.
    """

    __tablename__ = "beat_assignments"

    video_job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    beat_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str | None] = mapped_column(String(64))
    media_url: Mapped[str | None] = mapped_column(Text)
    preview_url: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(String(16))
    score: Mapped[float | None] = mapped_column(Float)
    attribution: Mapped[str | None] = mapped_column(Text)
    candidates: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
