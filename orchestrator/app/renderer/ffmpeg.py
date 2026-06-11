"""FFmpeg renderer — Ken Burns on photos, trim videos, text cards, mux audio."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..timeline import AudioPiece
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
# so Fontsize/margins are in pixels (sized off the short side in
# ``_subtitle_filter`` so portrait isn't oversized). WrapStyle=0 enables smart
# word wrapping so a wide chunk breaks onto another line instead of clipping.
# The style is white with a heavy black outline; the *active* word is recoloured
# yellow inline per event (see ``_subtitle_filter``), giving the word-by-word
# highlight. Applied via the ``ass`` filter inside the per-segment encode that
# already runs (no extra pass).
_ASS_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,{fontsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,{marginlr},{marginlr},{marginv},1

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
        download_concurrency: int = 8,
        threads: int = 2,
        preset: str = "veryfast",
        crf: int = 20,
        subprocess_timeout_s: float | None = None,
    ) -> None:
        self._temp_dir = Path(temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._segment_concurrency = max(1, segment_concurrency)
        self._download_concurrency = max(1, download_concurrency)
        self._threads = max(1, threads)
        self._preset = preset
        self._crf = crf
        self._subprocess_timeout_s = subprocess_timeout_s
        self._cpu_permits = threading.BoundedSemaphore(os.cpu_count() or 2)

    def _ffmpeg(self, args: list[str]) -> None:
        """Run ffmpeg with this renderer's configured hard subprocess timeout."""

        _run_ffmpeg(args, timeout_s=self._subprocess_timeout_s)

    def _encode_args(self, threads: int | None = None) -> list[str]:
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
            str(threads if threads is not None else self._threads),
        ]

    async def render(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
        *,
        width: int = 1280,
        height: int = 720,
        audio_windows: list[tuple[float, float]] | None = None,
        audio_pieces: list[AudioPiece] | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._render_sync,
            audio_path,
            timeline,
            output_path,
            width,
            height,
            audio_windows,
            audio_pieces,
        )

    def _render_sync(
        self,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
        width: int = 1280,
        height: int = 720,
        audio_windows: list[tuple[float, float]] | None = None,
        audio_pieces: list[AudioPiece] | None = None,
    ) -> str:
        work = self._temp_dir / Path(output_path).stem
        try:
            return self._render_work(
                work,
                audio_path,
                timeline,
                output_path,
                width,
                height,
                audio_windows,
                audio_pieces,
            )
        finally:
            # Always remove the intermediate work dir — even when the render
            # raises or is killed by the subprocess timeout — so a broken render
            # can't leak seg_*/src files and slowly fill the disk.
            if work != Path(output_path).parent:
                shutil.rmtree(work, ignore_errors=True)

    def _render_work(
        self,
        work: Path,
        audio_path: str,
        timeline: list[TimelineBeat],
        output_path: str,
        width: int = 1280,
        height: int = 720,
        audio_windows: list[tuple[float, float]] | None = None,
        audio_pieces: list[AudioPiece] | None = None,
    ) -> str:
        work.mkdir(parents=True, exist_ok=True)
        src_dir = work / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        segment_files = [work / f"seg_{i:03d}.mp4" for i in range(len(timeline))]

        # Two cooperating pools instead of one combined "download+encode" pool:
        #   * a network-bound DOWNLOAD pool (urlopen releases the GIL), and
        #   * a CPU-bound ENCODE pool (ffmpeg subprocesses).
        # As each download lands we immediately submit its dependent encode(s),
        # so the network waits of later beats overlap the ffmpeg work of earlier
        # ones (the old combined pool capped I/O concurrency at the CPU
        # concurrency and made each worker alternate wait->burn). Encodes write
        # to per-index seg files, so they never share state.
        #
        # Downloads are also DEDUPED by URL: when one asset is reused across
        # beats (motif reuse), it is fetched exactly once and every beat that
        # references it encodes from the same local file.
        url_to_indices: dict[str, list[int]] = {}
        text_indices: list[int] = []
        for i, beat in enumerate(timeline):
            url = beat.media_url if beat.kind in ("photo", "video") else None
            if url:
                url_to_indices.setdefault(url, []).append(i)
            else:
                text_indices.append(i)

        # Size the ENCODE pool to the host's cores. ffmpeg already gets
        # `render_threads` per process, and the worker layer may run
        # `render_concurrency` jobs at once, so running more parallel encodes
        # than cores just oversubscribes the CPU (x264 threads thrash on
        # context switches and every segment slows down). Cap at cpu_count and,
        # once we're at one encode per core, drop each encode to a single x264
        # thread so the product stays ~= cores. Downloads are network-bound, so
        # the DOWNLOAD pool keeps its full configured width.
        cpu = os.cpu_count() or 2
        enc_workers = min(self._segment_concurrency, cpu, max(1, len(timeline)))
        enc_threads = max(1, min(self._threads, max(1, cpu // enc_workers)))
        dl_workers = min(self._download_concurrency, max(1, len(url_to_indices)))
        logger.info(
            "render scheduling: %s beats (%s unique assets, %s text), "
            "encode=%sx%st download=%s on %s cpu",
            len(timeline),
            len(url_to_indices),
            len(text_indices),
            enc_workers,
            enc_threads,
            dl_workers,
            cpu,
        )

        # Per-phase timing so a slow render is diagnosable: are we network-bound
        # (sum of download seconds dominates) or CPU-bound (sum of encode
        # seconds dominates)? List.append is atomic under the GIL, so the pools
        # can record into these without an extra lock.
        download_secs: list[float] = []
        encode_secs: list[float] = []
        encoded_segments: list[tuple[int, str, float, float]] = []
        # url -> local file (or None if its download failed). Reused to mix the
        # per-word SFX audio of animated text-card clips into the final track.
        url_local: dict[str, Path | None] = {}

        def _timed_download(url: str, dest: Path) -> Path:
            t = time.monotonic()
            try:
                return _download_remote_asset(url, dest, timeout_s=120.0)
            finally:
                download_secs.append(time.monotonic() - t)

        def _timed_encode(idx: int, beat: TimelineBeat, path: Path | None) -> Path:
            t = time.monotonic()
            acquired = 0
            try:
                # Shared across concurrent render jobs in this process. A single
                # render can use all cores, but parallel renders share permits
                # instead of each scheduling a full cpu_count worth of x264 work.
                for _ in range(enc_threads):
                    self._cpu_permits.acquire()
                    acquired += 1
                return self._encode_beat(
                    idx, beat, path, work, width, height, threads=enc_threads
                )
            finally:
                for _ in range(acquired):
                    self._cpu_permits.release()
                elapsed = time.monotonic() - t
                encode_secs.append(elapsed)
                encoded_segments.append(
                    (idx, beat.kind, max(0.5, beat.end_s - beat.start_s), elapsed)
                )

        wall0 = time.monotonic()
        encode_pool = ThreadPoolExecutor(max_workers=enc_workers)
        download_pool = ThreadPoolExecutor(max_workers=dl_workers)
        encode_futures = []
        try:
            # Text/rhetorical beats need no download — encode them right away.
            for i in sorted(
                text_indices,
                key=lambda idx: timeline[idx].end_s - timeline[idx].start_s,
                reverse=True,
            ):
                encode_futures.append(
                    encode_pool.submit(_timed_encode, i, timeline[i], None)
                )
            # Kick off one download per unique URL.
            urls_by_encode_weight = sorted(
                url_to_indices,
                key=lambda url: max(
                    timeline[i].end_s - timeline[i].start_s for i in url_to_indices[url]
                ),
                reverse=True,
            )
            dl_future_to_url = {
                download_pool.submit(
                    _timed_download, url, src_dir / f"src_{k:03d}"
                ): url
                for k, url in enumerate(urls_by_encode_weight)
            }
            # As each download finishes, fan its local file out to every beat
            # that uses it; encodes start while remaining downloads continue.
            for dfut in as_completed(dl_future_to_url):
                url = dl_future_to_url[dfut]
                try:
                    local_path = dfut.result()
                except Exception as exc:  # noqa: BLE001 - one bad asset -> text fallback
                    logger.warning(
                        "asset download failed for %s: %s; affected beats use text fallback",
                        url,
                        exc,
                    )
                    local_path = None
                url_local[url] = local_path
                for i in sorted(
                    url_to_indices[url],
                    key=lambda idx: timeline[idx].end_s - timeline[idx].start_s,
                    reverse=True,
                ):
                    encode_futures.append(
                        encode_pool.submit(_timed_encode, i, timeline[i], local_path)
                    )
            for fut in encode_futures:
                fut.result()
        finally:
            download_pool.shutdown(wait=True)
            encode_pool.shutdown(wait=True)
        segments_wall = time.monotonic() - wall0
        logger.info(
            "render segments done in %.1fs wall | downloads: n=%s sum=%.1fs max=%.1fs | "
            "encodes: n=%s sum=%.1fs max=%.1fs",
            segments_wall,
            len(download_secs),
            sum(download_secs),
            max(download_secs, default=0.0),
            len(encode_secs),
            sum(encode_secs),
            max(encode_secs, default=0.0),
        )
        if encoded_segments:
            slowest = sorted(encoded_segments, key=lambda item: item[3], reverse=True)[:5]
            logger.info(
                "render slowest encodes: %s",
                "; ".join(
                    f"seg_{idx:03d} kind={kind} dur={duration:.1f}s encode={elapsed:.1f}s"
                    for idx, kind, duration, elapsed in slowest
                ),
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
        self._ffmpeg(
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
        if audio_pieces:
            # Standalone inserted beats splice silent gaps into the narration, so
            # the track is assembled from an ordered narration/silence list.
            narration_path = work / "narration.m4a"
            self._assemble_audio(audio_path, audio_pieces, narration_path)
            mux_audio_path = str(narration_path)
        elif audio_windows:
            narration_path = work / "narration.m4a"
            self._trim_audio(audio_path, audio_windows, narration_path)
            mux_audio_path = str(narration_path)
        else:
            mux_audio_path = audio_path

        # Beats whose clip carries its own audio (animated text cards' per-word
        # SFX) are mixed on top of the narration at their timeline offset. The
        # offset is the cumulative SEGMENT duration (matching the concatenated
        # video), so the SFX line up with the visuals.
        sfx_mix: list[tuple[float, Path]] = []
        offset = 0.0
        for beat in timeline:
            seg_dur = max(0.5, beat.end_s - beat.start_s)
            if beat.mix_audio and beat.media_url:
                local = url_local.get(beat.media_url)
                if local is not None:
                    sfx_mix.append((offset, local))
            offset += seg_dur

        self._mux_final(silent_video, mux_audio_path, sfx_mix, output_path)
        # The final mp4 lives at output_path (the mounted folder root); the work
        # dir only holds intermediate seg_*.mp4/silent.mp4 and is removed by the
        # caller's finally so it's cleaned up on success and failure alike.
        return output_path

    def _mux_final(
        self,
        silent_video: Path,
        mux_audio_path: str,
        sfx_mix: list[tuple[float, Path]],
        output_path: str,
    ) -> None:
        """Mux the assembled video with narration, mixing any per-beat SFX clips.

        Video is already a clean CFR H.264 stream, so it is stream-copied and
        only audio is (re)encoded; ``-shortest`` trims to the narration length.
        Streams are mapped explicitly (video from input 0, audio from the
        narration / mixed graph) so a narration that is itself a video file never
        leaks its video track into the output.

        When ``sfx_mix`` is empty this is the historical single-narration mux.
        Otherwise each SFX clip's audio is delayed to its beat offset and
        ``amix``-ed over the narration. If the mixed mux fails for any reason
        (e.g. a clip with no decodable audio track), we fall back to the plain
        narration mux so a render never fails just because of an SFX overlay.
        """

        simple = [
            "ffmpeg", "-y",
            "-i", str(silent_video),
            "-i", mux_audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
        if not sfx_mix:
            self._ffmpeg(simple)
            return

        inputs: list[str] = ["-i", str(silent_video), "-i", mux_audio_path]
        for _, path in sfx_mix:
            inputs += ["-i", str(path)]
        # Normalize every input to a common format before amix (amix needs a
        # shared sample rate/layout). Narration is input 1; SFX are inputs 2..N.
        filters = ["[1:a]aresample=48000,aformat=channel_layouts=stereo[narr]"]
        mix_labels = ["[narr]"]
        for k, (clip_offset, _) in enumerate(sfx_mix):
            ms = max(0, int(round(clip_offset * 1000)))
            filters.append(
                f"[{2 + k}:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"adelay={ms}|{ms},volume=0.8[sx{k}]"
            )
            mix_labels.append(f"[sx{k}]")
        # ``duration=first`` keeps the output as long as the narration (the first
        # input), so trailing SFX past the end are clipped rather than extending.
        filters.append(
            "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0[aout]"
        )
        mixed = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", ";".join(filters),
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
        try:
            self._ffmpeg(mixed)
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "SFX mix failed (%s SFX clips); falling back to narration-only mux: %s",
                len(sfx_mix),
                _stderr(exc),
            )
            self._ffmpeg(simple)

    def _assemble_audio(
        self,
        audio_path: str,
        pieces: list[AudioPiece],
        output_path: Path,
    ) -> None:
        """Assemble the narration track from ordered narration slices + silence.

        Used when the timeline contains standalone inserted beats (animated text
        cards with no narration): each such beat contributes a ``silence`` piece of
        its on-screen duration, so the muxed audio stays the same length as the
        video and the narration after the card resumes at the right moment. Every
        piece is normalized to 48 kHz stereo before ``concat`` so the formats
        match. Silence is generated with ``anullsrc`` trimmed to the gap length.
        """

        if not pieces:
            raise ValueError("audio_pieces must not be empty")
        parts: list[str] = []
        for i, piece in enumerate(pieces):
            if piece.kind == "silence":
                dur = max(0.0, float(piece.duration_s))
                parts.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f},"
                    f"asetpts=PTS-STARTPTS[a{i}]"
                )
            else:
                start = max(0.0, float(piece.start_s))
                end = max(start, float(piece.end_s))
                parts.append(
                    f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
                    f"aformat=sample_rates=48000:channel_layouts=stereo[a{i}]"
                )
        concat_inputs = "".join(f"[a{i}]" for i in range(len(pieces)))
        filter_complex = (
            ";".join(parts)
            + f";{concat_inputs}concat=n={len(pieces)}:v=0:a=1[outa]"
        )
        self._ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_path,
                "-filter_complex",
                filter_complex,
                "-map",
                "[outa]",
                "-c:a",
                "aac",
                str(output_path),
            ],
        )

    def _trim_audio(
        self,
        audio_path: str,
        windows: list[tuple[float, float]],
        output_path: Path,
    ) -> None:
        """Cut and concatenate narration windows into one AAC track."""

        if not windows:
            raise ValueError("audio_windows must not be empty")
        parts: list[str] = []
        for i, (start, end) in enumerate(windows):
            parts.append(
                f"[0:a]atrim=start={max(0.0, start):.3f}:end={max(start, end):.3f},"
                f"asetpts=PTS-STARTPTS[a{i}]"
            )
        concat_inputs = "".join(f"[a{i}]" for i in range(len(windows)))
        filter_complex = (
            ";".join(parts)
            + f";{concat_inputs}concat=n={len(windows)}:v=0:a=1[outa]"
        )
        self._ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                audio_path,
                "-filter_complex",
                filter_complex,
                "-map",
                "[outa]",
                "-c:a",
                "aac",
                str(output_path),
            ],
        )

    def _encode_beat(
        self,
        i: int,
        beat: TimelineBeat,
        local_path: Path | None,
        work: Path,
        width: int,
        height: int,
        *,
        threads: int | None = None,
    ) -> Path:
        """Encode one beat to ``seg_<i>.mp4`` from an already-downloaded asset.

        ``local_path`` is the on-disk media for media beats (``None`` for text
        beats, or when the upstream download failed). Any failure — missing
        asset or a bad ffmpeg encode — falls back to a text card so a single
        bad stock asset can never fail the whole job.
        """

        duration = max(0.5, beat.end_s - beat.start_s)
        seg_out = work / f"seg_{i:03d}.mp4"
        try:
            if beat.kind == "text" or beat.is_rhetorical:
                self._render_text_card(
                    beat.text_overlay or "...", duration, seg_out, width, height,
                    threads=threads,
                )
            elif local_path is None:
                raise RuntimeError("asset unavailable (download failed)")
            elif beat.kind == "photo":
                self._encode_ken_burns(
                    local_path, duration, seg_out, width, height,
                    overlay=beat.text_overlay, threads=threads,
                )
            else:
                self._encode_video_trim(
                    local_path, duration, seg_out, width, height,
                    overlay=beat.text_overlay, threads=threads,
                    source_in_s=beat.source_in_s,
                )
        except Exception as exc:  # noqa: BLE001 - one bad stock asset must not fail the job
            logger.warning(
                "media encode failed for seg_%03d (%s): %s; using text card fallback",
                i,
                beat.media_url,
                exc,
            )
            if isinstance(exc, subprocess.CalledProcessError):
                logger.debug("ffmpeg stderr: %s", _stderr(exc))
            self._render_text_card(
                beat.text_overlay or "...", duration, seg_out, width, height,
                threads=threads,
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

        # Scale the type off the SHORT side (min of w/h), not the height: in
        # portrait the height is the long side, so scaling by height made the
        # font ~2x too big for the available width and (with no wrapping) the
        # text overflowed and got clipped. min(w,h) gives a consistent caption
        # size across landscape/portrait/square. Side margins scale with width
        # so there's padding and the wrap budget is correct; WrapStyle=0 (smart
        # wrap) lets a wide chunk break onto a second line instead of clipping.
        base = min(width, height)
        ass = _ASS_TEMPLATE.format(
            width=width,
            height=height,
            fontsize=max(30, round(base * 0.085)),
            outline=max(2, round(base * 0.006)),
            shadow=max(1, round(base * 0.002)),
            marginlr=max(40, round(width * 0.06)),
            marginv=round(height * 0.32),
            events="\n".join(events),
        )
        ass_path = out.with_suffix(".ass")
        ass_path.write_text(ass, encoding="utf-8")
        # `original_size` MUST be passed (matching PlayResX/PlayResY) or libass's
        # aspect-ratio arithmetic mis-scales the fonts/positions whenever the
        # output isn't the renderer's assumed default aspect — captions then come
        # out stretched/offset on 9:16 and 1:1. Pinning it to the real frame size
        # sets pixel aspect = 1 and the correct storage size, so the captions
        # track every aspect ratio. (See ffmpeg `ass` filter `original_size` docs.)
        return f"ass={ass_path.as_posix()}:original_size={width}x{height}"

    def _render_text_card(
        self,
        text: str,
        duration: float,
        out: Path,
        width: int,
        height: int,
        *,
        threads: int | None = None,
    ) -> None:
        text_file = out.with_suffix(".txt")
        safe = text.replace("\r", " ").replace("\n", " ")[:120]
        text_file.write_text(safe, encoding="utf-8")
        # Scale font with frame height so text stays readable in portrait/landscape.
        fontsize = max(28, round(height * 0.058))
        self._ffmpeg(
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
                *self._encode_args(threads),
                "-t",
                str(duration),
                str(out),
            ],
        )

    def _encode_ken_burns(
        self,
        image_input: Path,
        duration: float,
        out: Path,
        width: int,
        height: int,
        *,
        overlay: str | None = None,
        threads: int | None = None,
    ) -> None:
        # ``image_input`` is the already-downloaded local photo (downloads run in
        # the shared, deduped download pool — see ``_render_sync``).
        vf = (
            f"{self._cover_filter(width, height)},"
            f"zoompan=z='min(zoom+0.0015,1.2)':d=125:fps={_FPS}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},"
            "setsar=1"
        )
        overlay_filter = self._subtitle_filter(overlay, out, width, height, duration)
        if overlay_filter:
            vf = f"{vf},{overlay_filter}"
        self._ffmpeg(
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
                *self._encode_args(threads),
                str(out),
            ],
        )

    def _encode_video_trim(
        self,
        video_input: Path,
        duration: float,
        out: Path,
        width: int,
        height: int,
        *,
        overlay: str | None = None,
        threads: int | None = None,
        source_in_s: float | None = None,
    ) -> None:
        # ``video_input`` is the already-downloaded local clip (downloads run in
        # the shared, deduped download pool — see ``_render_sync``). It lives in a
        # separate ``src/`` dir, so its .mp4 suffix can never collide with the
        # seg_NNN.mp4 output ("Output same as Input"). A local seekable file is
        # also required for ``-stream_loop -1`` / ``-ss`` to seek reliably.
        vf = f"{self._cover_filter(width, height)},setsar=1"
        overlay_filter = self._subtitle_filter(overlay, out, width, height, duration)
        if overlay_filter:
            vf = f"{vf},{overlay_filter}"
        if source_in_s is not None:
            # User-supplied source video: cut exactly this beat's window
            # ``[source_in_s, source_in_s+duration]`` so the footage stays in sync
            # with the narration. Input ``-ss`` (before ``-i``) is fast and seeks
            # to the nearest preceding keyframe; no stream loop — the source spans
            # the whole narration, so the window always exists.
            input_args = ["-ss", f"{max(0.0, source_in_s):.3f}", "-i", str(video_input)]
        else:
            # ``-stream_loop -1`` loops a stock clip shorter than its timeline slot
            # so it still fills the full duration (``-t`` clamps the output). This
            # keeps every slot exactly ``duration`` long, so the concatenated video
            # never ends up shorter than the audio.
            input_args = ["-stream_loop", "-1", "-i", str(video_input)]
        self._ffmpeg(
            [
                "ffmpeg",
                "-y",
                *input_args,
                "-t",
                str(duration),
                "-vf",
                vf,
                *self._encode_args(threads),
                str(out),
            ],
        )


def _stderr(exc: subprocess.CalledProcessError) -> str:
    stderr = exc.stderr
    if isinstance(stderr, bytes):
        return stderr.decode("utf-8", errors="replace")
    return str(stderr or "")


def _run_ffmpeg(args: list[str], *, timeout_s: float | None = None) -> None:
    cmd = args
    if args and Path(args[0]).name.lower().startswith("ffmpeg"):
        cmd = [args[0], "-hide_banner", "-loglevel", "error", *args[1:]]
    try:
        # ``timeout`` makes subprocess.run send SIGKILL on expiry, so a wedged
        # ffmpeg (corrupt input, filter deadlock) can never pin a render worker
        # or CPU forever — it raises TimeoutExpired and the render fails cleanly.
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out after %ss: %s", timeout_s, " ".join(cmd))
        raise
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg failed: %s", " ".join(cmd))
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
            # Stream straight to disk rather than buffering the whole file in
            # memory (HD/4K clips can be tens of MB each, and many download in
            # parallel) — overlaps the socket read with the disk write too.
            with urlopen(request, timeout=timeout_s) as response, open(local, "wb") as fh:
                shutil.copyfileobj(response, fh, length=1024 * 1024)
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
