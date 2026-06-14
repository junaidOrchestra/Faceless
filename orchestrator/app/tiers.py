"""Central tier definitions, per-tier limits, and the credit cost model.

This is the single editable place that defines what each subscription tier may
do (monthly credit grant, maximum video length, output resolution cap,
watermark) plus the helper that turns a rendered video's length into a credit
cost. Both the orchestrator's enforcement (before a render starts) and the
``GET /me`` surface read from here, so changing a limit in one spot changes it
everywhere.

Tiers are intentionally plain data (a frozen dataclass keyed in ``TIER_CONFIG``)
so they can be serialized to the frontend and swapped for a billing-driven
source later without touching the enforcement code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# "admin" is an internal-only tier (never advertised, no UI to obtain it). It is
# assigned out-of-band (set users.tier = 'admin' directly in the DB). It is a
# valid value of ``Tier`` so get_tier_config/enforcement recognize it, but it is
# deliberately excluded from ``PUBLIC_TIERS`` so it never appears in any public
# listing/pricing surface.
Tier = Literal["free", "individual", "professional", "admin"]
# Tiers users can actually sign up for / see. Admin is intentionally absent.
PUBLIC_TIERS: tuple[Tier, ...] = ("free", "individual", "professional")
# Backwards-compatible alias (older imports).
TIERS: tuple[Tier, ...] = PUBLIC_TIERS


@dataclass(frozen=True, slots=True)
class TierConfig:
    """Per-tier capabilities and limits.

    Attributes:
        name: The tier key (matches the ``users.tier`` enum value).
        label: Human-friendly name for the UI.
        monthly_credits: Credits granted at the start of each billing period.
        max_video_seconds: Hard cap on the rendered video length (input length).
        max_resolution_height: Output resolution cap (vertical pixels); the
            renderer must not exceed this height.
        watermark: Whether a watermark is burned into the output.
        max_projects: Maximum number of projects (videos) the user may keep at
            once. They must delete one before creating another. ``0`` = unlimited.
            This caps cumulative storage from a single account.
        max_concurrent_jobs: Maximum number of jobs the user may have actively
            processing (in the pre-render pipeline) at the same time. ``0`` =
            unlimited. Prevents one account from flooding the worker queues.
        daily_uploads: Maximum POST /videos (create/upload) requests per rolling
            day. ``0`` = unlimited. Caps the upstream transcribe/LLM/clip cost a
            single account can incur per day.
        unlimited_credits: When True, renders are never charged and the balance
            is never the gate (the credit pre-check + deduction are skipped).
            Used by the internal ``admin`` tier.
        features: Free-form capability flags surfaced to the UI.

    Note: ``max_video_seconds == 0`` means "no length limit" (see
    :func:`check_video_length`), matching the ``0 == unlimited`` convention used
    by the other caps.
    """

    name: Tier
    label: str
    monthly_credits: int
    max_video_seconds: int
    max_resolution_height: int
    watermark: bool
    features: tuple[str, ...]
    max_projects: int = 0
    max_concurrent_jobs: int = 0
    daily_uploads: int = 0
    unlimited_credits: bool = False


# --- The one editable place ------------------------------------------------
TIER_CONFIG: dict[Tier, TierConfig] = {
    "free": TierConfig(
        name="free",
        label="Free",
        monthly_credits=30,
        max_video_seconds=3600,
        max_resolution_height=720,
        watermark=True,
        max_projects=5,
        max_concurrent_jobs=1,
        daily_uploads=10,
        features=("stock_clips", "captions"),
    ),
    "individual": TierConfig(
        name="individual",
        label="Individual",
        monthly_credits=300,
        max_video_seconds=3600,
        max_resolution_height=1080,
        watermark=False,
        max_projects=50,
        max_concurrent_jobs=3,
        daily_uploads=100,
        features=("stock_clips", "captions", "no_watermark", "hd_export"),
    ),
    "professional": TierConfig(
        name="professional",
        label="Professional",
        monthly_credits=1500,
        max_video_seconds=3600,
        max_resolution_height=2160,
        watermark=False,
        max_projects=0,
        max_concurrent_jobs=10,
        daily_uploads=0,
        features=(
            "stock_clips",
            "captions",
            "no_watermark",
            "hd_export",
            "4k_export",
            "priority_render",
        ),
    ),
    # Internal-only tier. Not advertised, no self-serve path to obtain it; assign
    # by setting users.tier = 'admin' in the DB. Unlimited credits + no length
    # limit, but the watermark is intentionally kept on.
    "admin": TierConfig(
        name="admin",
        label="Admin",
        monthly_credits=0,  # unused: unlimited_credits short-circuits charging
        max_video_seconds=0,  # 0 = no length limit
        max_resolution_height=2160,
        watermark=True,
        max_projects=0,  # unlimited
        max_concurrent_jobs=0,  # unlimited
        daily_uploads=0,  # unlimited
        unlimited_credits=True,
        features=(
            "stock_clips",
            "captions",
            "hd_export",
            "4k_export",
            "priority_render",
        ),
    ),
}

DEFAULT_TIER: Tier = "free"

# --- Credit cost model -----------------------------------------------------
# One credit buys this many seconds of rendered video. The cost is rounded up so
# any non-zero render costs at least one credit. Kept here (not in env) so the
# pricing model lives next to the tier grants it is calibrated against.
SECONDS_PER_CREDIT: int = 15


def get_tier_config(tier: str | None) -> TierConfig:
    """Return the :class:`TierConfig` for ``tier`` (falls back to the free tier)."""

    if tier in TIER_CONFIG:
        return TIER_CONFIG[tier]  # type: ignore[index]
    return TIER_CONFIG[DEFAULT_TIER]


def credit_cost_for_seconds(seconds: float) -> int:
    """Convert a video length in seconds into an integer credit cost.

    Rounds up so a short clip still costs one credit; a zero/negative duration
    costs zero (nothing to render).
    """

    if seconds <= 0:
        return 0
    return max(1, math.ceil(seconds / SECONDS_PER_CREDIT))


@dataclass(frozen=True, slots=True)
class LimitViolation:
    """A single tier-limit breach, suitable for a 4xx error body."""

    code: str
    message: str


def check_video_length(tier: str | None, seconds: float) -> LimitViolation | None:
    """Return a violation if ``seconds`` exceeds the tier's max video length."""

    cfg = get_tier_config(tier)
    # max_video_seconds == 0 means "no limit" (e.g. the admin tier).
    if cfg.max_video_seconds and seconds > cfg.max_video_seconds:
        return LimitViolation(
            code="video_too_long",
            message=(
                f"Video is {seconds:.0f}s but the {cfg.label} tier allows at most "
                f"{cfg.max_video_seconds}s. Upgrade for longer videos."
            ),
        )
    return None


def check_project_quota(tier: str | None, current_count: int) -> LimitViolation | None:
    """Return a violation if creating one more project exceeds the tier's cap.

    ``max_projects == 0`` means unlimited. The cap bounds the cumulative storage
    a single account can hold, so the user must delete an existing project to
    make room.
    """

    cfg = get_tier_config(tier)
    if cfg.max_projects and current_count >= cfg.max_projects:
        return LimitViolation(
            code="project_limit_reached",
            message=(
                f"The {cfg.label} tier allows up to {cfg.max_projects} projects. "
                "Delete an existing project to create a new one, or upgrade for more."
            ),
        )
    return None


def check_concurrency(tier: str | None, active_count: int) -> LimitViolation | None:
    """Return a violation if another in-flight job exceeds the tier's cap.

    ``max_concurrent_jobs == 0`` means unlimited. Prevents one account from
    queuing many simultaneous jobs (each runs transcription/LLM/clip search).
    """

    cfg = get_tier_config(tier)
    if cfg.max_concurrent_jobs and active_count >= cfg.max_concurrent_jobs:
        n = cfg.max_concurrent_jobs
        return LimitViolation(
            code="too_many_active_jobs",
            message=(
                f"The {cfg.label} tier can process {n} "
                f"video{'s' if n != 1 else ''} at a time. "
                "Wait for an in-progress video to finish, or upgrade for more."
            ),
        )
    return None
