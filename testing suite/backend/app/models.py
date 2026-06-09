"""In-memory job/batch state and the request/response shapes for the API."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

# Ordered pipeline steps we time and surface in the UI.
STEP_KEYS: list[str] = [
    "fetch_audio",
    "create",
    "transcribe",
    "prepare",
    "clip_search",
    "render",
    "download",
]

STEP_LABELS: dict[str, str] = {
    "fetch_audio": "Get audio",
    "create": "Submit to orchestrator",
    "transcribe": "Transcribe narration",
    "prepare": "Prepare (vibe/aspect/quality)",
    "clip_search": "Find clips (LLM + CLIP)",
    "render": "Render video",
    "download": "Download result",
}

StepStatus = Literal["pending", "running", "done", "failed"]
JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class Step:
    key: str
    label: str
    status: StepStatus = "pending"
    started_at: float | None = None
    ended_at: float | None = None
    detail: str | None = None

    @property
    def duration_s(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.ended_at if self.ended_at is not None else time.time()
        return round(end - self.started_at, 2)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_s"] = self.duration_s
        return d


@dataclass
class Job:
    id: str
    # Per-video settings.
    theme_mode: str  # "script" | "vibe"
    video_format: str  # orchestrator format string, e.g. "youtube" / "tiktok"
    quality: str  # "sd" | "hd" | "max"
    subtitles: bool

    # Source: either a YouTube URL or a previously uploaded audio file.
    source_type: str = "youtube"  # "youtube" | "upload"
    url: str | None = None
    upload_path: str | None = None
    upload_filename: str | None = None
    vibe: str | None = None

    title: str | None = None
    status: JobStatus = "queued"
    error: str | None = None
    orchestrator_job_id: str | None = None
    duration_s: float | None = None
    beats: int | None = None
    output_size_bytes: int | None = None
    has_video: bool = False
    created_at: float = field(default_factory=time.time)
    steps: list[Step] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.steps:
            self.steps = [Step(k, STEP_LABELS[k]) for k in STEP_KEYS]

    def step(self, key: str) -> Step:
        return next(s for s in self.steps if s.key == key)

    def log(self, msg: str) -> None:
        self.logs.append(f"{time.strftime('%H:%M:%S')}  {msg}")

    @property
    def total_duration_s(self) -> float | None:
        durs = [s.duration_s for s in self.steps if s.duration_s is not None]
        return round(sum(durs), 2) if durs else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "url": self.url,
            "source": self.url or self.upload_filename or "(audio file)",
            "title": self.title,
            "theme_mode": self.theme_mode,
            "vibe": self.vibe,
            "video_format": self.video_format,
            "quality": self.quality,
            "subtitles": self.subtitles,
            "status": self.status,
            "error": self.error,
            "orchestrator_job_id": self.orchestrator_job_id,
            "duration_s": self.duration_s,
            "beats": self.beats,
            "output_size_bytes": self.output_size_bytes,
            "has_video": self.has_video,
            "total_duration_s": self.total_duration_s,
            "steps": [s.to_dict() for s in self.steps],
            "logs": self.logs[-50:],
        }


@dataclass
class Batch:
    id: str
    created_at: float = field(default_factory=time.time)
    job_ids: list[str] = field(default_factory=list)


class Store:
    """Thread/async-safe-enough in-memory store (single process)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self.batches: dict[str, Batch] = {}
        # upload_id -> {"path", "filename", "size"}
        self.uploads: dict[str, dict[str, Any]] = {}

    def add_upload(self, upload_id: str, path: str, filename: str, size: int) -> None:
        with self._lock:
            self.uploads[upload_id] = {"path": path, "filename": filename, "size": size}

    def get_upload(self, upload_id: str) -> dict[str, Any] | None:
        return self.uploads.get(upload_id)

    def new_batch(self) -> Batch:
        b = Batch(id=uuid.uuid4().hex[:12])
        with self._lock:
            self.batches[b.id] = b
        return b

    def add_job(self, job: Job, batch: Batch) -> None:
        with self._lock:
            self.jobs[job.id] = job
            batch.job_ids.append(job.id)

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def get_batch(self, batch_id: str) -> Batch | None:
        return self.batches.get(batch_id)

    def batch_dict(self, batch: Batch) -> dict[str, Any]:
        jobs = [self.jobs[j].to_dict() for j in batch.job_ids if j in self.jobs]
        done = sum(1 for j in jobs if j["status"] == "done")
        failed = sum(1 for j in jobs if j["status"] == "failed")
        return {
            "id": batch.id,
            "created_at": batch.created_at,
            "total": len(jobs),
            "done": done,
            "failed": failed,
            "in_progress": len(jobs) - done - failed,
            "jobs": jobs,
        }


# --- API request shapes -----------------------------------------------------


class VideoRequest(BaseModel):
    # Provide exactly one of `url` (YouTube) or `upload_id` (uploaded file).
    url: str | None = None
    upload_id: str | None = None
    theme_mode: Literal["script", "vibe"] = "script"
    vibe: str | None = None
    video_format: str = "youtube"
    quality: Literal["sd", "hd", "max"] = "hd"
    subtitles: bool = True


class BatchRequest(BaseModel):
    videos: list[VideoRequest] = Field(default_factory=list)
