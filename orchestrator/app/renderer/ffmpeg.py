"""FFmpeg renderer — Ken Burns on photos, trim videos, text cards, mux audio."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import textwrap
from pathlib import Path

from .base import Renderer, TimelineBeat

logger = logging.getLogger(__name__)


class FFmpegRenderer(Renderer):
    def __init__(self, temp_dir: str) -> None:
        self._temp_dir = Path(temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    async def render(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
    ) -> str:
        return await asyncio.to_thread(self._render_sync, audio_path, timeline, output_path)

    def _render_sync(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
    ) -> str:
        work = self._temp_dir / Path(output_path).stem
        work.mkdir(parents=True, exist_ok=True)
        segment_files: list[Path] = []

        for i, beat in enumerate(timeline):
            duration = max(0.5, beat.end_s - beat.start_s)
            seg_out = work / f"seg_{i:03d}.mp4"
            if beat.kind == "text" or beat.is_rhetorical:
                self._render_text_card(beat.text_overlay or "...", duration, seg_out)
            elif beat.kind == "photo":
                self._render_ken_burns(beat.media_url or "", duration, seg_out)
            else:
                self._render_video_trim(beat.media_url or "", duration, seg_out)
            segment_files.append(seg_out)

        concat_list = work / "concat.txt"
        concat_list.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in segment_files),
            encoding="utf-8",
        )
        silent_video = work / "silent.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(silent_video),
            ],
            check=True,
            capture_output=True,
        )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-i",
                audio_path,
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-shortest",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
        return output_path

    def _render_text_card(self, text: str, duration: float, out: Path) -> None:
        safe = textwrap.escape(text)[:80]
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=1280x720:d={duration}",
                "-vf",
                f"drawtext=text='{safe}':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=(h-text_h)/2",
                "-c:v",
                "libx264",
                "-t",
                str(duration),
                str(out),
            ],
            check=True,
            capture_output=True,
        )

    def _render_ken_burns(self, image_url: str, duration: float, out: Path) -> None:
        # For remote URLs FFmpeg can read directly; local paths must stay inside temp_dir.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                image_url,
                "-vf",
                "scale=1280:720,zoompan=z='min(zoom+0.0015,1.2)':d=125:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1280x720",
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                str(out),
            ],
            check=True,
            capture_output=True,
        )

    def _render_video_trim(self, video_url: str, duration: float, out: Path) -> None:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_url,
                "-t",
                str(duration),
                "-vf",
                "scale=1280:720",
                "-c:v",
                "libx264",
                "-an",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
