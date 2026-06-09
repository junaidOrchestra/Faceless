"use client";

import * as React from "react";
import { FileAudio, FileVideo } from "lucide-react";
import { cn } from "@/lib/utils";

type Kind = "audio" | "video";

const AUDIO_TYPES = [
  "audio/mpeg",
  "audio/mp3",
  "audio/wav",
  "audio/x-wav",
  "audio/mp4",
  "audio/m4a",
  "audio/webm",
];
const AUDIO_EXT = [".mp3", ".wav", ".m4a", ".weba"];
const VIDEO_TYPES = ["video/mp4", "video/webm", "video/quicktime", "video/x-matroska"];
const VIDEO_EXT = [".mp4", ".webm", ".mov", ".mkv"];

function matches(file: File, kind: Kind): boolean {
  const types = kind === "audio" ? AUDIO_TYPES : VIDEO_TYPES;
  const exts = kind === "audio" ? AUDIO_EXT : VIDEO_EXT;
  if (file.type && types.includes(file.type)) return true;
  // Some browsers send a bare type prefix (e.g. "video/3gpp"); accept the family.
  if (file.type.startsWith(`${kind}/`)) return true;
  const name = file.name.toLowerCase();
  return exts.some((ext) => name.endsWith(ext));
}

/** A drag-and-drop / browse zone for a single audio or video file. */
export function FileDrop({
  kind,
  busy,
  onFile,
}: {
  kind: Kind;
  busy: boolean;
  onFile: (file: File) => void;
}) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const accept = kind === "audio" ? [...AUDIO_TYPES, ...AUDIO_EXT] : [...VIDEO_TYPES, ...VIDEO_EXT];
  const hint = kind === "audio" ? "mp3, wav, m4a, or weba" : "mp4, webm, or mov";
  const Icon = kind === "audio" ? FileAudio : FileVideo;

  const handle = (file: File | undefined) => {
    if (!file) return;
    setError(null);
    if (!matches(file, kind)) {
      setError(
        kind === "audio"
          ? "That doesn't look like an audio file. Use mp3, wav, m4a, or weba."
          : "That doesn't look like a video file. Use mp4, webm, or mov.",
      );
      return;
    }
    onFile(file);
  };

  return (
    <div className="w-full">
      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handle(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "group relative flex w-full flex-col items-center justify-center gap-5 rounded-2xl border-2 border-dashed px-8 py-14 text-center transition-all",
          dragging
            ? "border-accent bg-accent/5 scale-[1.01]"
            : "border-hairline bg-panel hover:border-accent/50 hover:bg-panel-raised",
          busy && "pointer-events-none opacity-90",
        )}
      >
        <span
          className={cn(
            "grid size-16 place-items-center rounded-2xl border border-hairline bg-panel-raised text-faint transition-all group-hover:text-accent group-hover:border-accent/40",
            dragging && "text-accent border-accent/50",
          )}
        >
          <Icon className="size-7" />
        </span>
        <div className="space-y-1.5">
          <p className="font-heading text-xl font-semibold text-cream">
            Drop your {kind === "audio" ? "narration audio" : "video"} here
          </p>
          <p className="text-sm text-faint">
            or{" "}
            <span className="text-accent underline-offset-4 group-hover:underline">
              browse files
            </span>{" "}
            · {hint}
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={accept.join(",")}
          className="hidden"
          onChange={(e) => handle(e.target.files?.[0])}
        />
      </button>

      {error && <p className="mt-3 text-center text-sm text-destructive">{error}</p>}
    </div>
  );
}
