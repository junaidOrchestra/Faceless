"""FFmpeg renderer — Ken Burns on photos, trim videos, text cards, mux audio."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import Renderer, TimelineBeat

logger = logging.getLogger(__name__)

_HTTP_USER_AGENT = "faceless-video-orchestrator/0.1"

# A single download attempt makes the whole render fragile: one slow read or a
# transient DNS blip (e.g. "Name or service not known") would drop a beat to a
# text card. Retry a few times with backoff so a brief network hiccup doesn't
# cascade an entire run into text fallbacks.
_DOWNLOAD_MAX_ATTEMPTS = 4
_DOWNLOAD_BACKOFF_S = 1.5
_DOWNLOAD_BACKOFF_MAX_S = 8.0

# Every segment is normalized to this constant frame rate. Stock clips arrive at
# mixed rates (24/25/30/60 fps); concatenating those with `-c copy` produces a
# variable-frame-rate file whose timestamp jumps make players FREEZE a frame
# while the muxed audio keeps playing. Pinning one CFR everywhere (plus setsar=1
# and a CFR re-encode at concat) keeps the video in lockstep with the audio.
_FPS = 30

# ASS subtitle template for "Hormozi-style" captions. PlayResX/Y match the frame
# so Fontsize/margins are in pixels. The style is white with a heavy black
# outline; the *active* word is recoloured yellow inline per event (see
# ``_subtitle_filter``), giving the word-by-word highlight. Applied via the
# ``ass`` filter inside the per-segment encode that already runs (no extra pass).
_ASS_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,{fontsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,40,40,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""

# ASS BBGGRR colours.
_ASS_YELLOW = r"{\c&H00E6FF&}"  # RGB FFE600
_ASS_WHITE = r"{\c&HFFFFFF&}"


def _ass_ts(t: float) -> str:
    """Format seconds as an ASS timestamp ``H:MM:SS.cs`` (centisecond precision)."""

    cs = max(0, int(round(t * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


class FFmpegRenderer(Renderer):
    def __init__(
        self,
        temp_dir: str,
        *,
        segment_concurrency: int = 4,
        threads: int = 2,
        preset: str = "veryfast",
        crf: int = 20,
    ) -> None:
        self._temp_dir = Path(temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._segment_concurrency = max(1, segment_concurrency)
        self._threads = max(1, threads)
        self._preset = preset
        self._crf = crf

    def _encode_args(self) -> list[str]:
        """Identical libx264 output args shared by every segment encoder.

        Keeping these byte-for-byte consistent across photo/video/text segments
        (codec, preset, CRF, pixel format, frame rate, CFR mode, and the mp4
        track timescale) is what lets the concat step join them with ``-c copy``
        instead of re-encoding the entire timeline a second time. Each segment is
        therefore encoded exactly once — faster *and* without the extra
        generation loss the old double-encode introduced.
        """

        return [
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            self._preset,
            "-crf",
            str(self._crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(_FPS),
            "-fps_mode",
            "cfr",
            "-video_track_timescale",
            "90000",
            "-threads",
            str(self._threads),
        ]

    async def render(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
        *,
        width: int = 1280,
        height: int = 720,
    ) -> str:
        return await asyncio.to_thread(
            self._render_sync, audio_path, timeline, output_path, width, height
        )

    def _render_sync(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
        width: int = 1280,
        height: int = 720,
    ) -> str:
        work = self._temp_dir / Path(output_path).stem
        work.mkdir(parents=True, exist_ok=True)
        segment_files = [work / f"seg_{i:03d}.mp4" for i in range(len(timeline))]

        # Render every beat (download + encode) in a bounded thread pool instead
        # of one-at-a-time. Each task is subprocess/IO bound (urlopen + ffmpeg),
        # so threads overlap the network waits and saturate the cores. Output
        # paths are per-index, so the tasks never touch shared state.
        workers = min(self._segment_concurrency, max(1, len(timeline)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(
                pool.map(
                    lambda item: self._render_segment(
                        item[0], item[1], work, width, height
                    ),
                    list(enumerate(timeline)),
                )
            )

        concat_list = work / "concat.txt"
        concat_list.write_text(
            "".join(f"file '{p.as_posix()}'\n" for p in segment_files),
            encoding="utf-8",
        )
        silent_video = work / "silent.mp4"
        # Stream-copy the segments (no re-encode). Each segment was already
        # encoded once at a forced constant 30fps with identical libx264 params
        # and a fixed mp4 timescale (see `_encode_args`), so the joined timeline
        # is continuous CFR without a second full-length encode — this avoids the
        # extra generation loss and roughly halves the encode CPU. The old
        # mixed-fps freeze risk is already handled at the per-segment encode.
        _run_ffmpeg(
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
        )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        # Video is already a clean CFR H.264 stream, so copy it and only encode
        # audio; `-shortest` trims to whichever track ends first.
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-i",
                audio_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                output_path,
            ],
        )
        # The final mp4 lives at output_path (the mounted folder root); the work
        # dir only holds intermediate seg_*.mp4/silent.mp4 — remove it so the
        # output folder stays clean and easy to browse.
        if work != Path(output_path).parent:
            shutil.rmtree(work, ignore_errors=True)
        return output_path

    def _render_segment(
        self, i: int, beat: TimelineBeat, work: Path, width: int, height: int
    ) -> Path:
        """Render one beat to ``seg_<i>.mp4``; fall back to a text card on failure."""

        duration = max(0.5, beat.end_s - beat.start_s)
        seg_out = work / f"seg_{i:03d}.mp4"
        try:
            if beat.kind == "text" or beat.is_rhetorical:
                self._render_text_card(
                    beat.text_overlay or "...", duration, seg_out, width, height
                )
            elif beat.kind == "photo":
                self._render_ken_burns(
                    beat.media_url or "",
                    duration,
                    seg_out,
                    width,
                    height,
                    overlay=beat.text_overlay,
                )
            else:
                self._render_video_trim(
                    beat.media_url or "",
                    duration,
                    seg_out,
                    width,
                    height,
                    overlay=beat.text_overlay,
                )
        except Exception as exc:  # noqa: BLE001 - one bad stock asset must not fail the job
            logger.warning(
                "media render failed for seg_%03d (%s): %s; using text card fallback",
                i,
                beat.media_url,
                exc,
            )
            if isinstance(exc, subprocess.CalledProcessError):
                logger.debug("ffmpeg stderr: %s", _stderr(exc))
            self._render_text_card(
                beat.text_overlay or "...", duration, seg_out, width, height
            )
        return seg_out

    @staticmethod
    def _cover_filter(width: int, height: int) -> str:
        """Scale to cover WxH then center-crop — fills the frame without stretching."""

        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

    def _subtitle_filter(
        self, text: str | None, out: Path, width: int, height: int, duration: float
    ) -> str | None:
        """Build "Hormozi-style" word-by-word captions for one segment.

        The beat text is upper-cased and shown a few words at a time; within each
        group the *currently spoken* word is highlighted yellow while the rest of
        the group stays white, advancing word by word. Rendered as a per-segment
        ASS file (big bold caps, heavy outline, centred) and applied via the
        ``ass`` filter in the per-segment encode that already runs — no extra
        pass. Word timing is approximated by splitting the beat duration evenly
        (we don't persist per-word timestamps).
        """

        cleaned = " ".join((text or "").replace("\r", " ").replace("\n", " ").split()).upper()
        # Drop ASS override/escape chars so words can't break the markup.
        tokens = [
            w.translate({ord("{"): None, ord("}"): None, ord("\\"): None})
            for w in cleaned.split()
        ]
        tokens = [w for w in tokens if w][:60]
        if not tokens:
            return None

        # Group into short word chunks so only a few show at once (the punchy pop),
        # with the highlight advancing one word at a time inside each chunk.
        chunk_size = 3
        chunks = [tokens[i : i + chunk_size] for i in range(0, len(tokens), chunk_size)]
        nchunks = len(chunks)
        chunk_span = max(duration / nchunks, 0.2)

        events: list[str] = []
        for ci, chunk in enumerate(chunks):
            chunk_start = ci * chunk_span
            word_span = max(chunk_span / len(chunk), 0.05)
            for wi in range(len(chunk)):
                w_start = chunk_start + wi * word_span
                # Last word of the last chunk lingers a touch past the end so it
                # never flickers off a frame early due to rounding.
                if ci == nchunks - 1 and wi == len(chunk) - 1:
                    w_end = duration + 0.5
                else:
                    w_end = chunk_start + (wi + 1) * word_span
                line = " ".join(
                    (_ASS_YELLOW if k == wi else _ASS_WHITE) + word
                    for k, word in enumerate(chunk)
                )
                events.append(
                    f"Dialogue: 0,{_ass_ts(w_start)},{_ass_ts(w_end)},Caption,,0,0,0,,{line}"
                )

        ass = _ASS_TEMPLATE.format(
            width=width,
            height=height,
            fontsize=max(30, round(height * 0.085)),
            outline=max(2, round(height * 0.006)),
            shadow=max(1, round(height * 0.002)),
            marginv=round(height * 0.32),
            events="\n".join(events),
        )
        ass_path = out.with_suffix(".ass")
        ass_path.write_text(ass, encoding="utf-8")
        return f"ass={ass_path.as_posix()}"

    def _render_text_card(
        self, text: str, duration: float, out: Path, width: int, height: int
    ) -> None:
        text_file = out.with_suffix(".txt")
        safe = text.replace("\r", " ").replace("\n", " ")[:120]
        text_file.write_text(safe, encoding="utf-8")
        # Scale font with frame height so text stays readable in portrait/landscape.
        fontsize = max(28, round(height * 0.058))
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={width}x{height}:r={_FPS}:d={duration}",
                "-vf",
                (
                    f"drawtext=textfile={text_file.as_posix()}:"
                    f"fontcolor=white:fontsize={fontsize}:"
                    "x=(w-text_w)/2:y=(h-text_h)/2:"
                    "expansion=none,setsar=1"
                ),
                *self._encode_args(),
                "-t",
                str(duration),
                str(out),
            ],
        )

    def _render_ken_burns(
        self,
        image_url: str,
        duration: float,
        out: Path,
        width: int,
        height: int,
        *,
        overlay: str | None = None,
    ) -> None:
        # Download remote photos first. Rendering directly from Pexels URLs makes
        # the whole job vulnerable to one transient network/HTTP read failure.
        image_input = _download_remote_asset(image_url, out.with_suffix(".image"))
        vf = (
            f"{self._cover_filter(width, height)},"
            f"zoompan=z='min(zoom+0.0015,1.2)':d=125:fps={_FPS}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},"
            "setsar=1"
        )
        overlay_filter = self._subtitle_filter(overlay, out, width, height, duration)
        if overlay_filter:
            vf = f"{vf},{overlay_filter}"
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image_input),
                "-vf",
                vf,
                "-t",
                str(duration),
                *self._encode_args(),
                str(out),
            ],
        )

    def _render_video_trim(
        self,
        video_url: str,
        duration: float,
        out: Path,
        width: int,
        height: int,
        *,
        overlay: str | None = None,
    ) -> None:
        # Download the clip first. Streaming straight from a stock CDN makes the
        # whole job vulnerable to a transient network drop mid-read (TLS pull
        # errors / premature EOF -> a cascade of corrupt-NAL decode failures).
        # ``-stream_loop -1`` also needs a seekable local file to re-loop
        # reliably; it cannot rewind a remote HTTP stream.
        # Download to a distinct "<stem>_src" base so the local file can never
        # resolve to the output path (a video URL's .mp4 suffix would otherwise
        # collide with seg_NNN.mp4 -> "Output same as Input" failure).
        video_input = _download_remote_asset(
            video_url, out.with_name(f"{out.stem}_src"), timeout_s=120.0
        )
        # ``-stream_loop -1`` loops the source so a stock clip shorter than its
        # timeline slot still fills the full duration (with ``-t`` clamping the
        # output). This keeps every slot exactly ``duration`` long, so the
        # concatenated video never ends up shorter than the audio.
        vf = f"{self._cover_filter(width, height)},setsar=1"
        overlay_filter = self._subtitle_filter(overlay, out, width, height, duration)
        if overlay_filter:
            vf = f"{vf},{overlay_filter}"
        _run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(video_input),
                "-t",
                str(duration),
                "-vf",
                vf,
                *self._encode_args(),
                str(out),
            ],
        )


def _stderr(exc: subprocess.CalledProcessError) -> str:
    stderr = exc.stderr
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace")
    return str(stderr or "")


def _run_ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg failed: %s", " ".join(args))
        logger.error("ffmpeg stderr: %s", _stderr(exc))
        raise


def _download_remote_asset(url: str, target: Path, *, timeout_s: float = 30.0) -> Path:
    if not url.startswith(("http://", "https://")):
        return Path(url)

    suffix = Path(urlparse(url).path).suffix or ".bin"
    local = target.with_suffix(suffix)
    request = Request(url, headers={"User-Agent": _HTTP_USER_AGENT})

    last_exc: Exception | None = None
    for attempt in range(1, _DOWNLOAD_MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=timeout_s) as response:
                local.write_bytes(response.read())
            return local
        except Exception as exc:  # noqa: BLE001 - retry any transient network/DNS error
            last_exc = exc
            if attempt >= _DOWNLOAD_MAX_ATTEMPTS:
                break
            delay = min(
                _DOWNLOAD_BACKOFF_S * (2 ** (attempt - 1)),
                _DOWNLOAD_BACKOFF_MAX_S,
            )
            logger.warning(
                "asset download failed (attempt %s/%s) for %s: %s; retrying in %.1fs",
                attempt,
                _DOWNLOAD_MAX_ATTEMPTS,
                url,
                exc,
                delay,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc
