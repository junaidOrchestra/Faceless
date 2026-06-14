"use client";

import * as React from "react";
import { Loader2, Music, Sparkles, Wand2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { findChosenAsset, useEditorStore } from "@/lib/store";
import { getEffectOverlays } from "@/lib/api";
import type { EffectOverlayClip } from "@/lib/orchestrator";
import type { Aspect, EffectSoundId, EffectVisualId, VideoJob } from "@/lib/types";
import { ASPECT_DIMS } from "@/lib/animated-text";
import {
  DEFAULT_SOUND,
  DEFAULT_VISUAL,
  EFFECT_SOUNDS,
  EFFECT_VISUALS,
  effectDuration,
  effectLabel,
  scheduleEffectSfx,
} from "@/lib/effects";
import {
  loadImageDrawable,
  loadOverlayVideo,
  loadVideoFrameDrawable,
  neutralDrawable,
  type Drawable,
} from "@/lib/effect-media";
import { cn } from "@/lib/utils";

const ASPECT_PREVIEW: Record<Aspect, string> = {
  "9:16": "mx-auto aspect-[9/16] h-[42vh]",
  "16:9": "w-full aspect-video",
  "1:1": "mx-auto aspect-square h-[36vh]",
};

type FreezeSource =
  | { kind: "none" }
  | { kind: "image"; url: string }
  | { kind: "video"; url: string; atS: number };

// Resolve what to freeze behind a sound-only insert: the previous beat's frame.
function resolveFreeze(job: VideoJob | null, position: number | null): FreezeSource {
  if (!job || position == null) return { kind: "none" };
  const prev = job.beats.find((b) => b.index === position - 1);
  if (!prev) return { kind: "none" };
  const asset = findChosenAsset(prev);
  if (!asset) return { kind: "none" };
  if (asset.kind === "photo") {
    const url = asset.thumbUrl || asset.mediaUrl;
    return url ? { kind: "image", url } : { kind: "none" };
  }
  // Video: prefer a still poster; otherwise grab the frame near the beat's end.
  if (asset.thumbUrl) return { kind: "image", url: asset.thumbUrl };
  if (asset.mediaUrl) {
    const atS = (asset.sourceInS ?? 0) + Math.max(0, prev.to - prev.from - 0.1);
    return { kind: "video", url: asset.mediaUrl, atS };
  }
  return { kind: "none" };
}

async function loadFreezeDrawable(f: FreezeSource): Promise<Drawable> {
  try {
    if (f.kind === "image") return await loadImageDrawable(f.url);
    if (f.kind === "video") return await loadVideoFrameDrawable(f.url, f.atS);
  } catch {
    /* fall through to neutral */
  }
  return neutralDrawable();
}

async function loadVisualDrawable(overlayUrl: string | null): Promise<Drawable> {
  if (overlayUrl) {
    try {
      return await loadOverlayVideo(overlayUrl);
    } catch {
      /* fall through to neutral */
    }
  }
  return neutralDrawable();
}

// Canvas preview that mirrors exactly what the recorder produces: it draws the
// same Drawable (real overlay clip / frozen frame / neutral) and plays the same
// SFX on a loop, so the preview matches the final clip.
function EffectPreview({
  visual,
  sound,
  overlayUrl,
  freeze,
  durationS,
  aspect,
  loading,
}: {
  visual: EffectVisualId;
  sound: EffectSoundId;
  overlayUrl: string | null;
  freeze: FreezeSource;
  durationS: number;
  aspect: Aspect;
  loading: boolean;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const freezeKey = freeze.kind === "none" ? "none" : `${freeze.kind}:${freeze.url}`;

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let cancelled = false;
    let drawable: Drawable | null = null;
    let raf = 0;
    let audio: AudioContext | null = null;
    let initialTimer = 0;

    try {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctor) {
        audio = new Ctor();
        void audio.resume().catch(() => {});
      }
    } catch {
      audio = null;
    }

    // Play the SFX ONCE (not on a loop). Re-invoked on click to replay. The
    // visual keeps looping (overlay clip / static freeze) — only the sound is
    // one-shot, matching the recorded clip.
    const playSoundOnce = () => {
      if (!audio || sound === "none") return;
      if (audio.state !== "running") void audio.resume().catch(() => {});
      scheduleEffectSfx(audio, audio.destination, sound, audio.currentTime + 0.03);
    };
    canvas.addEventListener("click", playSoundOnce);
    // Auto-play once when the preview (re)opens — best effort; if the browser
    // blocks autoplay, the first click triggers it.
    initialTimer = window.setTimeout(playSoundOnce, 140);

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const W = Math.max(2, Math.round(rect.width * dpr));
      const H = Math.max(2, Math.round(rect.height * dpr));
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      if (drawable) drawable.draw(ctx, W, H);
      else {
        ctx.fillStyle = "#0a0a0d";
        ctx.fillRect(0, 0, W, H);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    const wanted = visual !== "none" ? loadVisualDrawable(overlayUrl) : loadFreezeDrawable(freeze);
    void wanted.then((d) => {
      if (cancelled) {
        d.dispose?.();
        return;
      }
      drawable = d;
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      window.clearTimeout(initialTimer);
      canvas.removeEventListener("click", playSoundOnce);
      drawable?.dispose?.();
      void audio?.close().catch(() => {});
    };
    // freezeKey captures the freeze source identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visual, sound, overlayUrl, freezeKey, durationS]);

  return (
    <div className="relative">
      <canvas
        ref={canvasRef}
        title="Click to replay the sound"
        className={cn(
          "cursor-pointer rounded-xl border border-hairline bg-black",
          ASPECT_PREVIEW[aspect],
        )}
      />
      {loading && (
        <div className="absolute inset-0 grid place-items-center rounded-xl bg-black/40">
          <Loader2 className="size-6 animate-spin text-white/80" />
        </div>
      )}
    </div>
  );
}

function OptionRow({
  active,
  label,
  description,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  description: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border px-3 py-2 text-left transition-all",
        active
          ? "border-accent bg-accent/10"
          : "border-hairline hover:border-hairline/80 hover:bg-panel-raised/40",
      )}
    >
      <span
        className={cn(
          "flex items-center gap-1.5 text-sm font-medium",
          active ? "text-accent" : "text-cream",
        )}
      >
        {icon}
        {label}
      </span>
      <span className="mt-0.5 block text-[11px] leading-snug text-faint">{description}</span>
    </button>
  );
}

export function NewEffectDialog({
  open,
  position,
  onClose,
}: {
  open: boolean;
  position: number | null;
  onClose: () => void;
}) {
  const job = useEditorStore((s) => s.job);
  const jobAspect = job?.aspect ?? "9:16";
  const insertEffectBeat = useEditorStore((s) => s.insertEffectBeat);

  const [sound, setSound] = React.useState<EffectSoundId>(DEFAULT_SOUND);
  const [visual, setVisual] = React.useState<EffectVisualId>(DEFAULT_VISUAL);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // Curated overlay clips per category, pre-fetched server-side and served from
  // the DB (no live search). null = not loaded yet; {} = loaded but empty.
  const [overlays, setOverlays] = React.useState<Record<
    string,
    EffectOverlayClip[]
  > | null>(null);

  const freeze = React.useMemo(() => resolveFreeze(job, position), [job, position]);
  const durationS = effectDuration(visual, sound);
  const canAdd = !(sound === "none" && visual === "none");
  const overlayUrl = visual === "none" ? null : overlays?.[visual]?.[0]?.mediaUrl ?? null;
  const overlayLoading = visual !== "none" && overlays === null;

  // Load the curated overlay set once when the dialog opens (cached for the
  // session). Picking a visual just reads from this map — no per-visual fetch.
  React.useEffect(() => {
    if (!open || overlays !== null) return;
    let cancelled = false;
    void getEffectOverlays()
      .then((map) => {
        if (!cancelled) setOverlays(map);
      })
      .catch(() => {
        if (!cancelled) setOverlays({});
      });
    return () => {
      cancelled = true;
    };
  }, [open, overlays]);

  const handleAdd = async () => {
    if (position === null || !canAdd) return;
    setBusy(true);
    setError(null);
    try {
      const dims = ASPECT_DIMS[jobAspect];
      const drawable =
        visual !== "none" ? await loadVisualDrawable(overlayUrl) : await loadFreezeDrawable(freeze);
      const { recordEffectClip } = await import("@/lib/animated-recorder");
      const { blob } = await recordEffectClip({
        width: dims.w,
        height: dims.h,
        durationS,
        sound,
        visual: drawable,
      });
      const label = effectLabel(visual, sound);
      const meta = `${visual}+${sound}`;
      await insertEffectBeat(position, label, durationS, blob, meta);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the effect. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Add sound &amp; effect</DialogTitle>
          <p className="text-sm text-faint">
            Pick a sound, a visual, or both. Visuals use real footage. A quick
            tip: a little goes a long way — one well-placed whoosh beats ten.
          </p>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_460px]">
          <div className="min-w-0">
            <EffectPreview
              visual={visual}
              sound={sound}
              overlayUrl={overlayUrl}
              freeze={freeze}
              durationS={durationS}
              aspect={jobAspect}
              loading={overlayLoading}
            />
            <p className="mt-2 text-center text-[11px] text-faint">
              Live preview · {durationS.toFixed(2)}s
              {visual === "none" ? " · freezes the previous frame" : " · real footage"} ·
              click to replay the sound
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="min-w-0">
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-cream">
                <Wand2 className="size-3.5" /> Visual
              </p>
              <div className="max-h-[40vh] space-y-1.5 overflow-y-auto pr-1">
                {EFFECT_VISUALS.map((v) => (
                  <OptionRow
                    key={v.id}
                    active={visual === v.id}
                    label={v.label}
                    description={v.description}
                    icon={<Wand2 className="size-3.5" />}
                    onClick={() => setVisual(v.id)}
                  />
                ))}
              </div>
            </div>
            <div className="min-w-0">
              <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-cream">
                <Music className="size-3.5" /> Sound
              </p>
              <div className="max-h-[40vh] space-y-1.5 overflow-y-auto pr-1">
                {EFFECT_SOUNDS.map((s) => (
                  <OptionRow
                    key={s.id}
                    active={sound === s.id}
                    label={s.label}
                    description={s.description}
                    icon={<Music className="size-3.5" />}
                    onClick={() => setSound(s.id)}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}
        <Button
          variant="primary"
          className="w-full"
          onClick={handleAdd}
          disabled={busy || !canAdd}
        >
          {busy ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Recording {durationS.toFixed(2)}s…
            </>
          ) : (
            <>
              <Sparkles className="size-4" /> Add {effectLabel(visual, sound)}
            </>
          )}
        </Button>
        {!canAdd && (
          <p className="text-center text-[11px] text-faint">
            Choose at least a sound or a visual.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
