"use client";

import * as React from "react";
import { Circle, Mic, RotateCcw, Square, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Kind = "audio" | "video";

/** Pick the best container the browser will actually record to. */
function pickMimeType(kind: Kind): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  const candidates =
    kind === "audio"
      ? ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]
      : ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];
  return candidates.find((c) => MediaRecorder.isTypeSupported(c));
}

function extFor(mime: string | undefined): string {
  if (!mime) return ".webm";
  if (mime.includes("mp4")) return ".mp4";
  if (mime.includes("ogg")) return ".ogg";
  return ".webm";
}

function fmt(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

type Phase = "idle" | "requesting" | "recording" | "recorded";

/** Capture narration directly from the mic (audio) or camera (video). */
export function Recorder({
  kind,
  busy,
  onFile,
}: {
  kind: Kind;
  busy: boolean;
  onFile: (file: File) => void;
}) {
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [error, setError] = React.useState<string | null>(null);
  const [elapsed, setElapsed] = React.useState(0);
  const [previewUrl, setPreviewUrl] = React.useState<string | null>(null);

  const streamRef = React.useRef<MediaStream | null>(null);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const chunksRef = React.useRef<Blob[]>([]);
  const mimeRef = React.useRef<string | undefined>(undefined);
  const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const liveVideoRef = React.useRef<HTMLVideoElement>(null);
  const previewUrlRef = React.useRef<string | null>(null);

  const stopStream = React.useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const clearTimer = React.useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Tear everything down on unmount.
  React.useEffect(() => {
    return () => {
      clearTimer();
      stopStream();
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = async () => {
    setError(null);
    if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("Recording isn't supported in this browser.");
      return;
    }
    setPhase("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia(
        kind === "audio" ? { audio: true } : { audio: true, video: { facingMode: "user" } },
      );
      streamRef.current = stream;
      if (kind === "video" && liveVideoRef.current) {
        liveVideoRef.current.srcObject = stream;
        await liveVideoRef.current.play().catch(() => {});
      }

      const mime = pickMimeType(kind);
      mimeRef.current = mime;
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeRef.current || "application/octet-stream" });
        const url = URL.createObjectURL(blob);
        setPreviewUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          previewUrlRef.current = url;
          return url;
        });
        setPhase("recorded");
        stopStream();
      };
      recorderRef.current = recorder;
      recorder.start();

      setElapsed(0);
      clearTimer();
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
      setPhase("recording");
    } catch (e) {
      stopStream();
      setPhase("idle");
      const name = e instanceof DOMException ? e.name : "";
      setError(
        name === "NotAllowedError"
          ? `Permission denied. Allow ${kind === "audio" ? "microphone" : "camera & microphone"} access to record.`
          : name === "NotFoundError"
            ? `No ${kind === "audio" ? "microphone" : "camera"} found.`
            : "Couldn't start recording. Check your device and try again.",
      );
    }
  };

  const stop = () => {
    clearTimer();
    recorderRef.current?.stop();
  };

  const reset = () => {
    clearTimer();
    stopStream();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrlRef.current = null;
    setPreviewUrl(null);
    setElapsed(0);
    setError(null);
    setPhase("idle");
  };

  const use = () => {
    if (chunksRef.current.length === 0) return;
    const blob = new Blob(chunksRef.current, {
      type: mimeRef.current || "application/octet-stream",
    });
    const ext = extFor(mimeRef.current);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const file = new File([blob], `recording-${ts}${ext}`, { type: blob.type });
    onFile(file);
  };

  const Icon = kind === "audio" ? Mic : Video;
  const showLiveVideo = kind === "video" && (phase === "recording" || phase === "requesting");

  return (
    <div className="w-full">
      <div className="flex flex-col items-center justify-center gap-5 rounded-2xl border-2 border-dashed border-hairline bg-panel px-8 py-12 text-center">
        {/* Live camera preview (video) or pulsing mic (audio) while recording. */}
        <div
          className={cn(
            "relative grid w-full max-w-xs place-items-center overflow-hidden rounded-2xl border border-hairline bg-panel-raised",
            kind === "video" ? "aspect-video" : "aspect-[3/1]",
          )}
        >
          {showLiveVideo ? (
            <video
              ref={liveVideoRef}
              muted
              playsInline
              className="absolute inset-0 size-full object-cover"
            />
          ) : phase === "recorded" && previewUrl ? (
            kind === "video" ? (
              <video src={previewUrl} controls playsInline className="absolute inset-0 size-full object-cover" />
            ) : (
              <audio src={previewUrl} controls className="w-[88%]" />
            )
          ) : (
            <span
              className={cn(
                "grid size-14 place-items-center rounded-full border border-hairline bg-panel text-faint",
                phase === "recording" && "animate-pulse text-accent border-accent/50",
              )}
            >
              <Icon className="size-6" />
            </span>
          )}

          {phase === "recording" && (
            <span className="absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-black/55 px-2.5 py-1 text-xs font-medium text-white">
              <Circle className="size-2.5 animate-pulse fill-red-500 text-red-500" />
              {fmt(elapsed)}
            </span>
          )}
        </div>

        <div className="space-y-1.5">
          <p className="font-heading text-lg font-semibold text-cream">
            {phase === "recorded"
              ? "Review your recording"
              : phase === "recording"
                ? `Recording ${kind}…`
                : `Record ${kind === "audio" ? "your narration" : "yourself talking"}`}
          </p>
          <p className="text-sm text-faint">
            {phase === "recorded"
              ? "Use it as your narration, or record again."
              : kind === "audio"
                ? "We transcribe the audio and find your beats."
                : "Only the audio track is used — your video stays faceless."}
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-2.5">
          {phase === "idle" && (
            <Button variant="primary" onClick={start} disabled={busy}>
              <Icon className="size-4" />
              Start recording
            </Button>
          )}
          {phase === "requesting" && (
            <Button variant="primary" disabled>
              Requesting access…
            </Button>
          )}
          {phase === "recording" && (
            <Button variant="primary" onClick={stop}>
              <Square className="size-4 fill-current" />
              Stop
            </Button>
          )}
          {phase === "recorded" && (
            <>
              <Button variant="ghost" onClick={reset} disabled={busy}>
                <RotateCcw className="size-4" />
                Re-record
              </Button>
              <Button variant="primary" onClick={use} disabled={busy}>
                Use recording
              </Button>
            </>
          )}
        </div>
      </div>

      {error && <p className="mt-3 text-center text-sm text-destructive">{error}</p>}
    </div>
  );
}
