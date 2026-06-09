"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { FileAudio, FileVideo, Loader2, Mic, Video } from "lucide-react";
import { uploadAudio } from "@/lib/api";
import { rememberPreviewAudio } from "@/lib/preview-audio";
import { FileDrop } from "@/components/file-drop";
import { Recorder } from "@/components/recorder";
import { cn } from "@/lib/utils";

type Mode = "audio-file" | "video-file" | "record-audio" | "record-video";

const TABS: { mode: Mode; label: string; icon: typeof FileAudio }[] = [
  { mode: "audio-file", label: "Audio file", icon: FileAudio },
  { mode: "video-file", label: "Video file", icon: FileVideo },
  { mode: "record-audio", label: "Record audio", icon: Mic },
  { mode: "record-video", label: "Record video", icon: Video },
];

// An upload that never completes (huge file / wedged proxy) must not pin the
// home screen on "Uploading…" forever.
const UPLOAD_TIMEOUT_MS = 180_000;

export function MediaInput() {
  const router = useRouter();
  const [mode, setMode] = React.useState<Mode>("audio-file");
  const [busy, setBusy] = React.useState(false);
  const [busyName, setBusyName] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);

  React.useEffect(() => () => abortRef.current?.abort(), []);

  const cancel = React.useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const submit = React.useCallback(
    async (file: File) => {
      setError(null);
      setBusy(true);
      setBusyName(file.name);
      const controller = new AbortController();
      abortRef.current = controller;
      const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
      try {
        const { videoJobId } = await uploadAudio(file, controller.signal);
        // The synced preview plays the narration from this blob (the audio track
        // for video inputs), so remember it for any media file.
        rememberPreviewAudio(videoJobId, file);
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
            <p className="text-sm text-faint">Transcribing and finding your beats.</p>
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
