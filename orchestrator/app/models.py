"""Orchestrator Postgres models — video jobs, beats, and per-beat assignments.

``VideoJob`` drives the job lifecycle and ``GET /videos/{id}``. ``Beat`` and
``BeatAssignment`` record the breakdown of a finished job (each spoken beat, its
timing/text, and the media clip selected for it) so ``GET /videos/{id}/beats``
can replay what the pipeline produced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    """A user mirror keyed by the Supabase auth id (the JWT ``sub``, a UUID).

    Authentication lives in Supabase; this row is our own copy of the identity
    plus all app-owned state (tier, credit balance). ``credits`` is the running
    balance kept in sync with the append-only ``credit_transactions`` ledger.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Start of the period the current free/paid grant belongs to. Used by the
    # check-on-use monthly reset to detect when a new period has begun.
    credits_granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Project(Base):
    """A single video belonging to a user (one project == one video)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditTransaction(Base):
    """Append-only credit ledger. ``users.credits`` is the running balance."""

    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Signed change: +grant / -spend / +refund.
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Feedback(Base):
    """A user-submitted suggestion, improvement, bug report, or note.

    Kept deliberately simple and append-only: every submission is a row we can
    triage later. ``user_id`` ties it to the authenticated submitter; ``email``
    is an optional reply-to (defaults to the account email) so we can follow up.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="suggestion")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional 1-5 satisfaction signal captured alongside the note.
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lightweight context to help us reproduce/triage: the page the user was on
    # and their browser UA. Never required.
    page: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VideoJob(Base):
    __tablename__ = "video_jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Ownership + project linkage (added with accounts). ``owner_id`` mirrors the
    # Supabase user id; ``project_id`` ties the job to its Project row.
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    # Per-word timing for "tighten audio" (filler-word removal + caption sync).
    # A list of {"t": text, "s": start_s, "e": end_s, "f": is_filler}. Nullable so
    # older jobs (transcribed before this column) still load.
    words: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Beat origin. "narration" (default) = a transcript-derived beat backed by a
    # narration time window [start_s, end_s]. "insert" = a user-added standalone
    # animated text card with NO narration: it contributes ``duration_s`` of video
    # and an equal silent gap in the muxed audio (its own per-word SFX is mixed on
    # top). ``start_s == end_s`` for inserts (the narration time it sits at).
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="narration")
    # On-screen / silent-gap duration in seconds for "insert" beats. NULL/0 for
    # narration beats, whose duration comes from their narration window instead.
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)


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
