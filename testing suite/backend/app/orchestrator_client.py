"""Thin async client for the Faceless Video orchestrator API.

Mirrors the calls seemless makes (see seemless/lib/orchestrator.ts and the
Next.js proxy routes), but drives the *whole* pipeline end-to-end without any
human in the loop:

    create (no format)  ->  prepare  ->  render  ->  download

The bearer token is injected on every request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from .config import Settings


class OrchestratorError(RuntimeError):
    pass


class OrchestratorClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._s.orchestrator_token}"}

    def _url(self, path: str) -> str:
        return f"{self._s.orchestrator_url}{path}"

    # -- create --------------------------------------------------------------
    async def create_video(self, audio_path: str) -> str:
        """Upload narration audio and return the new video_job_id.

        Deliberately omits ``format`` so the job pauses at ``transcribed`` and we
        can supply the output choices via /prepare (matching the divided flow).
        """
        p = Path(audio_path)
        data: dict[str, str] = {
            "sources": self._s.sources,
            "pexels_key": self._s.pexels_key,
        }
        if self._s.pixabay_key:
            data["pixabay_key"] = self._s.pixabay_key
        with p.open("rb") as fh:
            files = {"audio": (p.name, fh, "audio/mpeg")}
            res = await self._http.post(
                self._url("/videos"),
                headers=self._headers,
                data=data,
                files=files,
            )
        if res.status_code not in (200, 202):
            raise OrchestratorError(f"create_video {res.status_code}: {res.text}")
        return res.json()["video_job_id"]

    # -- status --------------------------------------------------------------
    async def get_status(self, job_id: str) -> dict[str, Any]:
        res = await self._http.get(self._url(f"/videos/{job_id}"), headers=self._headers)
        if res.status_code != 200:
            raise OrchestratorError(f"get_status {res.status_code}: {res.text}")
        return res.json()

    # -- prepare -------------------------------------------------------------
    async def prepare(
        self,
        job_id: str,
        *,
        video_format: str,
        quality: str,
        subtitles: bool,
        theme: dict[str, Any],
    ) -> None:
        body = {
            "format": video_format,
            "quality": quality,
            "subtitles": subtitles,
            "theme": theme,
        }
        res = await self._http.post(
            self._url(f"/videos/{job_id}/prepare"),
            headers=self._headers,
            json=body,
        )
        # 409 = already prepared / past the setup window (a benign race).
        # 404/405 = legacy orchestrator without /prepare; clip search auto-starts.
        if res.status_code in (200, 202, 404, 405, 409):
            return
        raise OrchestratorError(f"prepare {res.status_code}: {res.text}")

    # -- render --------------------------------------------------------------
    async def render(self, job_id: str) -> None:
        """Start the render using the default selected candidate for every beat."""
        res = await self._http.post(
            self._url(f"/videos/{job_id}/render"), headers=self._headers
        )
        if res.status_code not in (200, 202):
            raise OrchestratorError(f"render {res.status_code}: {res.text}")

    # -- beats (for a quick sanity count) ------------------------------------
    async def get_beats(self, job_id: str) -> list[dict[str, Any]]:
        res = await self._http.get(
            self._url(f"/videos/{job_id}/beats"), headers=self._headers
        )
        if res.status_code != 200:
            return []
        return res.json().get("beats", [])

    # -- download ------------------------------------------------------------
    async def download(self, job_id: str, dest: str) -> int:
        """Stream the finished MP4 to ``dest``. Returns the byte size written."""
        total = 0
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._http.stream(
            "GET",
            self._url(f"/videos/{job_id}/download"),
            headers=self._headers,
            follow_redirects=True,
        ) as res:
            if res.status_code != 200:
                body = await res.aread()
                raise OrchestratorError(
                    f"download {res.status_code}: {body.decode(errors='ignore')}"
                )
            with dest_path.open("wb") as fh:
                async for chunk in res.aiter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
                    total += len(chunk)
        if total == 0:
            raise OrchestratorError("download produced an empty file")
        return total


def parse_sources(raw: str) -> list[str]:
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(x) for x in val]
    except json.JSONDecodeError:
        pass
    return [raw]
