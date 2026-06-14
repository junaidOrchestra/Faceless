"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { FileAudio, FileVideo, Loader2, Mic, Video } from "lucide-react";
import { uploadAudio } from "@/lib/api";
import { startVideoWithEarlyTranscribe } from "@/lib/background-upload";
import {
  rememberPreviewAudio,
  rememberUploadedMedia,
  prewarmPreviewAudio,
} from "@/lib/preview-audio";
import { persistUploadedMedia } from "@/lib/media-cache";
import { FileDrop } from "@/components/file-drop";
import { Recorder } from "@/components/recorder";
import { cn } from "@/lib/utils";
import { formatUploadLimits, MAX_UPLOAD_BYTES } from "@/lib/upload-limits";

type Mode = "audio-file" | "video-file" | "record-audio" | "record-video";

const TABS: { mode: Mode; label: string; icon: typeof FileAudio }[] = [
  { mode: "audio-file", label: "Audio file", icon: FileAudio },
  { mode: "video-file", label: "Video file", icon: FileVideo },
  { mode: "record-audio", label: "Record audio", icon: Mic },
  { mode: "record-video", label: "Record video", icon: Video },
];

// Large 3 GB uploads can legitimately take a long time on slow connections, but
// a wedged proxy still needs a backstop.
const UPLOAD_TIMEOUT_MS = 2 * 60 * 60 * 1000;

export function MediaInput() {
  const router = useRouter();
  const [mode, setMode] = React.useState<Mode>("audio-file");
  const [busy, setBusy] = React.useState(false);
  const [busyName, setBusyName] = React.useState<string | null>(null);
  const [progress, setProgress] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const cancel = React.useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const submit = React.useCallback(
    async (file: File) => {
      setError(null);
      if (file.size > MAX_UPLOAD_BYTES) {
        setError(`That file is too large. Upload ${formatUploadLimits()}.`);
        return;
      }
      setBusy(true);
      setBusyName(file.name);
      setProgress(0);
      const controller = new AbortController();
      abortRef.current = controller;
      const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
      try {
        // For a video, extract its audio in the browser and start transcription
        // immediately while the full video uploads in the background — the editor
        // opens right away. Falls back to a regular upload when extraction isn't
        // possible (or direct-to-bucket storage isn't configured).
        let videoJobId: string | null = null;
        if (file.type.startsWith("video/")) {
          videoJobId = await startVideoWithEarlyTranscribe(file, controller.signal);
        }
        if (!videoJobId) {
          ({ videoJobId } = await uploadAudio(file, controller.signal, (pct) =>
            setProgress(pct),
          ));
        }
        // The synced preview plays the narration from this blob (the audio track
        // for video inputs), so remember it for any media file.
        const previewUrl = rememberPreviewAudio(videoJobId, file);
        // Decode the narration now (the file is already local) so the editor's
        // preview opens instantly instead of waiting on a decode.
        prewarmPreviewAudio(previewUrl);
        // For a video, serve the editor preview + beat thumbnails from this exact
        // local file instead of the cloud copy: remember an in-session object URL
        // and persist the bytes to IndexedDB so it survives a refresh / revisit.
        if (file.type.startsWith("video/")) {
          rememberUploadedMedia(videoJobId, file);
          void persistUploadedMedia(videoJobId, file);
        }
        try {
          sessionStorage.setItem(`sf:name:${videoJobId}`, file.name);
        } catch {
          // ignore storage failures
        }
        router.push(`/edit/${videoJobId}`);
      } catch (e) {
        setBusy(false);
        if (controller.signal.aborted) {
          setError("Upload canceled or timed out. Please try again.");
        } else {
          setError(e instanceof Error ? e.message : "Upload failed. Try again.");
        }
      } finally {
        clearTimeout(timer);
        abortRef.current = null;
      }
    },
    [router],
  );

  return (
    <div className="w-full space-y-4">
      <div
        role="tablist"
        aria-label="Narration input"
        className="grid grid-cols-2 gap-1.5 rounded-2xl border border-hairline bg-panel p-1.5 sm:grid-cols-4"
      >
        {TABS.map((t) => {
          const active = mode === t.mode;
          return (
            <button
              key={t.mode}
              role="tab"
              type="button"
              aria-selected={active}
              disabled={busy}
              onClick={() => {
                setError(null);
                setMode(t.mode);
              }}
              className={cn(
                "flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium transition-all disabled:opacity-50",
                active
                  ? "bg-panel-raised text-cream shadow-[0_0_0_1px_rgba(244,183,64,0.35)]"
                  : "text-faint hover:text-cream hover:bg-panel-raised/60",
              )}
            >
              <t.icon className={cn("size-4", active && "text-accent")} />
              {t.label}
            </button>
          );
        })}
      </div>

      {busy ? (
        <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-hairline bg-panel px-8 py-16 text-center">
          <span className="grid size-16 place-items-center rounded-2xl border border-hairline bg-panel-raised">
            <Loader2 className="size-7 animate-spin text-accent" />
          </span>
          <div className="space-y-1">
            <p className="font-heading text-lg font-semibold text-cream">
              Uploading {busyName}…
            </p>
            <p className="text-sm text-faint">
              {progress > 0 && progress < 100
                ? `${Math.round(progress)}% uploaded`
                : "Transcribing and finding your beats."}
            </p>
          </div>
          <button
            type="button"
            onClick={cancel}
            className="text-xs font-medium text-faint underline-offset-2 hover:text-cream hover:underline"
          >
            Cancel
          </button>
        </div>
      ) : mode === "audio-file" ? (
        <FileDrop kind="audio" busy={busy} onFile={submit} />
      ) : mode === "video-file" ? (
        <FileDrop kind="video" busy={busy} onFile={submit} />
      ) : mode === "record-audio" ? (
        <Recorder kind="audio" busy={busy} onFile={submit} />
      ) : (
        <Recorder kind="video" busy={busy} onFile={submit} />
      )}

      {error && <p className="text-center text-sm text-destructive">{error}</p>}
    </div>
  );
}
