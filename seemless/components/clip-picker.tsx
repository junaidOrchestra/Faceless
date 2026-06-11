"use client";

import * as React from "react";
import { Check, Loader2, Play, Search, Sparkles, UploadCloud, Video } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { searchClips, uploadAnimatedClip, uploadOwnClip } from "@/lib/api";
import { useEditorStore } from "@/lib/store";
import type { Aspect, AnimatedTextConfig, AnimatedTextSpeed, Asset, Beat } from "@/lib/types";
import {
  ANIMATED_PALETTES,
  ANIMATED_SOUNDS,
  ANIMATED_STYLES,
  DEFAULT_ANIMATED,
  ASPECT_DIMS,
  TYPING_SPEED_PRESETS,
  activeRelWord,
  durationForSpeed,
  drawAnimatedFrame,
  relWordsForBeat,
  relWordsForTextAtSpeed,
  type RelWord,
} from "@/lib/animated-text";
import { playSfx } from "@/lib/sfx";
import { cn, fmtRange } from "@/lib/utils";

const ASPECT_PREVIEW: Record<Aspect, string> = {
  "9:16": "mx-auto aspect-[9/16] h-[44vh]",
  "16:9": "w-full aspect-video",
  "1:1": "mx-auto aspect-square h-[38vh]",
};

function AssetCard({
  asset,
  selected,
  onSelect,
}: {
  asset: Asset;
  selected: boolean;
  onSelect: () => void;
}) {
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const [active, setActive] = React.useState(false);
  const isVideo = asset.kind === "video" && Boolean(asset.mediaUrl);
  const posterUrl = asset.thumbUrl || undefined;
  const sourceInS = asset.sourceInS ?? 0;
  // Without a still-image poster (e.g. the user's own uploaded footage), append
  // a media fragment so the browser loads and paints the frame at 0.1s as the
  // static thumbnail instead of showing a black tile.
  const videoSrc =
    isVideo && !posterUrl ? `${asset.mediaUrl}#t=${Math.max(0.1, sourceInS)}` : asset.mediaUrl;

  const play = () => {
    if (!isVideo) return;
    setActive(true);
  };
  const stop = () => {
    if (!isVideo) return;
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = sourceInS;
    }
    setActive(false);
  };

  return (
    <button
      type="button"
      onClick={onSelect}
      onMouseEnter={play}
      onMouseLeave={stop}
      onFocus={play}
      onBlur={stop}
      className={cn(
        "group relative aspect-square overflow-hidden rounded-lg border bg-canvas transition-all hover:-translate-y-0.5",
        selected ? "border-accent ring-2 ring-accent" : "border-hairline hover:border-hairline/80",
      )}
    >
      {isVideo && active ? (
        <video
          ref={videoRef}
          src={videoSrc}
          poster={posterUrl}
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
          className="size-full object-cover"
          onLoadedMetadata={(e) => {
            e.currentTarget.currentTime = sourceInS;
          }}
        />
      ) : posterUrl ? (
        <img src={posterUrl} alt="" className="size-full object-cover" loading="lazy" />
      ) : isVideo ? (
        <video
          src={videoSrc}
          muted
          playsInline
          preload="metadata"
          className="size-full object-cover"
          onLoadedMetadata={(e) => {
            e.currentTarget.currentTime = sourceInS;
          }}
        />
      ) : (
        <img src={asset.thumbUrl} alt="" className="size-full object-cover" loading="lazy" />
      )}
      {asset.kind === "video" && (
        <span className="absolute right-1.5 top-1.5 grid size-5 place-items-center rounded bg-black/60 text-white">
          <Video className="size-3" />
        </span>
      )}
      {isVideo && !active && (
        <span className="pointer-events-none absolute inset-0 grid place-items-center">
          <span className="grid size-8 place-items-center rounded-full bg-black/55 text-white backdrop-blur transition-opacity group-hover:opacity-0">
            <Play className="size-3.5 translate-x-px fill-current" />
          </span>
        </span>
      )}
      <span className="absolute bottom-1.5 left-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide text-white/90 backdrop-blur">
        {asset.source}
      </span>
      {selected && (
        <span className="absolute right-1.5 bottom-1.5 grid size-5 place-items-center rounded-full bg-accent text-accent-foreground">
          <Check className="size-3" />
        </span>
      )}
    </button>
  );
}

function TextCardEditor({ beat, onDone }: { beat: Beat; onDone: () => void }) {
  const setOverlay = useEditorStore((s) => s.setOverlay);
  const [text, setText] = React.useState(beat.overlay ?? beat.text.slice(0, 60));

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-hairline bg-gradient-to-br from-panel-raised to-canvas p-6">
        <p className="mx-auto max-w-xs text-center font-heading text-lg font-semibold text-cream">
          {text || "Your caption"}
        </p>
      </div>
      <div>
        <Textarea
          value={text}
          maxLength={60}
          onChange={(e) => setText(e.target.value.slice(0, 60))}
          placeholder="Type the on-screen text…"
          className="min-h-[72px]"
        />
        <p className="mt-1 text-right font-mono text-[11px] text-faint">{text.length}/60</p>
      </div>
      <Button
        variant="primary"
        className="w-full"
        onClick={() => {
          setOverlay(beat.index, text.trim());
          onDone();
        }}
        disabled={!text.trim()}
      >
        Save text card
      </Button>
    </div>
  );
}

function YourLibraryTab({ beat, onDone }: { beat: Beat; onDone: () => void }) {
  const addCandidate = useEditorStore((s) => s.addCandidate);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);

  const handle = async (file: File) => {
    setBusy(true);
    const asset = await uploadOwnClip(beat.index, file);
    addCandidate(beat.index, asset, true);
    setBusy(false);
    onDone();
  };

  return (
    <div className="space-y-3">
      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          const f = e.dataTransfer.files?.[0];
          if (f) void handle(f);
        }}
        className="flex w-full flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed border-accent/50 bg-accent/5 px-6 py-12 text-center transition-all hover:border-accent hover:bg-accent/10"
      >
        <span className="grid size-14 place-items-center rounded-2xl bg-accent text-accent-foreground shadow-lg">
          {busy ? <Loader2 className="size-6 animate-spin" /> : <UploadCloud className="size-6" />}
        </span>
        <div>
          <p className="font-heading text-base font-semibold text-cream">
            Use your own footage
          </p>
          <p className="text-sm text-faint">
            Drop a photo or video clip — it&apos;s instantly assigned to this beat.
          </p>
        </div>
        <Badge variant="accent">your library</Badge>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*,video/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void handle(f);
        }}
      />
    </div>
  );
}

// Live, looping canvas preview of the animated card (same renderer + SFX the
// recorder uses, so the preview matches the final clip). Plays per-word sounds
// to the speakers as each word appears.
function AnimatedPreview({
  config,
  words,
  durationS,
  aspect,
}: {
  config: AnimatedTextConfig;
  words: RelWord[];
  durationS: number;
  aspect: Aspect;
}) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let audio: AudioContext | null = null;
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

    // Browser autoplay policy can leave the context suspended (silent SFX). Resume
    // it on the next user gesture anywhere in the dialog, so picking a sound or
    // hovering then clicking reliably unlocks audio for the preview.
    const resumeAudio = () => {
      if (audio && audio.state !== "running") void audio.resume().catch(() => {});
    };
    window.addEventListener("pointerdown", resumeAudio);
    window.addEventListener("keydown", resumeAudio);

    let raf = 0;
    const start = performance.now();
    let lastWord = -1;
    const loop = () => {
      const elapsed = ((performance.now() - start) / 1000) % durationS;
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const W = Math.max(2, Math.round(rect.width * dpr));
      const H = Math.max(2, Math.round(rect.height * dpr));
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      drawAnimatedFrame(ctx, {
        width: W,
        height: H,
        style: config.style,
        palette: config.palette,
        clockS: elapsed,
        durationS,
        words,
      });
      const active = activeRelWord(words, elapsed);
      if (active !== lastWord && active >= 0 && audio && config.sound !== "none") {
        if (audio.state !== "running") void audio.resume().catch(() => {});
        playSfx(audio, audio.destination, config.sound);
      }
      lastWord = active;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointerdown", resumeAudio);
      window.removeEventListener("keydown", resumeAudio);
      void audio?.close().catch(() => {});
    };
  }, [config, words, durationS]);

  return (
    <canvas ref={canvasRef} className={cn("rounded-xl border border-hairline bg-black", ASPECT_PREVIEW[aspect])} />
  );
}

function OptionPills<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 text-xs text-faint">{label}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button
            key={o.id}
            type="button"
            onClick={() => onChange(o.id)}
            className={cn(
              "rounded-lg border px-2.5 py-1.5 text-xs transition-all",
              value === o.id
                ? "border-accent bg-accent/10 text-accent"
                : "border-hairline text-faint hover:border-hairline/80 hover:text-cream",
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AnimatedTextTab({
  beat,
  aspect,
  jobId,
  onDone,
}: {
  beat: Beat;
  aspect: Aspect;
  jobId: string;
  onDone: () => void;
}) {
  const addCandidate = useEditorStore((s) => s.addCandidate);
  // Seed from the beat's current animated pick (re-editing) or the defaults.
  const current = beat.candidates.find((c) => c.id === beat.chosenAssetId)?.animated;
  const [config, setConfig] = React.useState<AnimatedTextConfig>(
    current ?? { ...DEFAULT_ANIMATED },
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const isInsert = (beat.kind ?? "narration") === "insert";
  const durationS = Math.max(0.6, isInsert ? beat.durationS ?? beat.to - beat.from : beat.to - beat.from);
  const words = React.useMemo(
    () => relWordsForBeat(beat.words, isInsert ? 0 : beat.from, beat.text, durationS),
    [beat.words, beat.from, beat.text, durationS, isInsert],
  );

  const handleUse = async () => {
    setBusy(true);
    setError(null);
    try {
      const dims = ASPECT_DIMS[aspect];
      const { recordAnimatedClip } = await import("@/lib/animated-recorder");
      const { blob } = await recordAnimatedClip({
        width: dims.w,
        height: dims.h,
        config,
        words,
        durationS,
      });
      const asset = await uploadAnimatedClip(jobId, beat.index, blob, config);
      addCandidate(beat.index, asset, true);
      onDone();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not create the animated clip. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_220px]">
      <div className="min-w-0">
        <AnimatedPreview config={config} words={words} durationS={durationS} aspect={aspect} />
        <p className="mt-2 text-center text-[11px] text-faint">
          Live preview · plays the sound as each word appears
        </p>
      </div>
      <div className="space-y-4">
        <OptionPills
          label="Background"
          value={config.style}
          options={ANIMATED_STYLES}
          onChange={(style) => setConfig((c) => ({ ...c, style }))}
        />
        <OptionPills
          label="Colour"
          value={config.palette}
          options={ANIMATED_PALETTES.map((p) => ({ id: p.id, label: p.label }))}
          onChange={(palette) => setConfig((c) => ({ ...c, palette }))}
        />
        <OptionPills
          label="Word sound"
          value={config.sound}
          options={ANIMATED_SOUNDS}
          onChange={(sound) => setConfig((c) => ({ ...c, sound }))}
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <Button variant="primary" className="w-full" onClick={handleUse} disabled={busy}>
          {busy ? (
            <>
              <Loader2 className="size-4 animate-spin" /> Recording {durationS.toFixed(1)}s…
            </>
          ) : (
            <>
              <Sparkles className="size-4" /> Use this animated card
            </>
          )}
        </Button>
        {busy && (
          <p className="text-center text-[11px] text-faint">
            Rendering this beat to a clip — takes about {durationS.toFixed(0)}s.
          </p>
        )}
      </div>
    </div>
  );
}

export function NewAnimatedBeatDialog({
  open,
  position,
  onClose,
}: {
  open: boolean;
  position: number | null;
  onClose: () => void;
}) {
  const jobAspect = useEditorStore((s) => s.job?.aspect ?? "9:16");
  const insertAnimatedBeat = useEditorStore((s) => s.insertAnimatedBeat);
  const [text, setText] = React.useState("");
  const [speed, setSpeed] = React.useState<AnimatedTextSpeed>("normal");
  const [config, setConfig] = React.useState<AnimatedTextConfig>({ ...DEFAULT_ANIMATED });
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const words = React.useMemo(
    () => relWordsForTextAtSpeed(text, speed),
    [text, speed],
  );
  const durationS = React.useMemo(
    () => durationForSpeed(words.length, speed),
    [words.length, speed],
  );

  const handleAdd = async () => {
    const trimmed = text.trim();
    if (!trimmed || position === null) return;
    setBusy(true);
    setError(null);
    try {
      const dims = ASPECT_DIMS[jobAspect];
      const { recordAnimatedClip } = await import("@/lib/animated-recorder");
      const { blob } = await recordAnimatedClip({
        width: dims.w,
        height: dims.h,
        config,
        words,
        durationS,
      });
      await insertAnimatedBeat(position, trimmed, durationS, blob, config, words);
      onClose();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not add the animated text beat. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add animated text beat</DialogTitle>
          <p className="text-sm text-faint">
            This inserts a standalone card. Narration pauses here; only the word
            sound plays, then narration resumes.
          </p>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_240px]">
          <div className="min-w-0 space-y-3">
            <AnimatedPreview
              config={config}
              words={words}
              durationS={durationS}
              aspect={jobAspect}
            />
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, 280))}
              placeholder="Type the words to reveal on screen..."
              className="min-h-[96px]"
            />
            <p className="text-right font-mono text-[11px] text-faint">
              {words.length} words · {durationS.toFixed(1)}s
            </p>
          </div>
          <div className="space-y-4">
            <OptionPills
              label="Writing speed"
              value={speed}
              options={TYPING_SPEED_PRESETS}
              onChange={setSpeed}
            />
            <OptionPills
              label="Background"
              value={config.style}
              options={ANIMATED_STYLES}
              onChange={(style) => setConfig((c) => ({ ...c, style }))}
            />
            <OptionPills
              label="Colour"
              value={config.palette}
              options={ANIMATED_PALETTES.map((p) => ({ id: p.id, label: p.label }))}
              onChange={(palette) => setConfig((c) => ({ ...c, palette }))}
            />
            <OptionPills
              label="Word sound"
              value={config.sound}
              options={ANIMATED_SOUNDS}
              onChange={(sound) => setConfig((c) => ({ ...c, sound }))}
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button
              variant="primary"
              className="w-full"
              onClick={handleAdd}
              disabled={busy || !text.trim() || words.length === 0}
            >
              {busy ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Recording {durationS.toFixed(1)}s...
                </>
              ) : (
                <>
                  <Sparkles className="size-4" /> Add text beat
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ClipPicker({
  beat,
  open,
  onClose,
}: {
  beat: Beat | null;
  open: boolean;
  onClose: () => void;
}) {
  const chooseAsset = useEditorStore((s) => s.chooseAsset);
  const addCandidate = useEditorStore((s) => s.addCandidate);
  const jobAspect = useEditorStore((s) => s.job?.aspect ?? "9:16");
  const jobId = useEditorStore((s) => s.job?.id ?? "");
  // Transient state starts fresh on every open because the parent remounts this
  // component with a key tied to the open beat (see editor page).
  const [query, setQuery] = React.useState("");
  const [searching, setSearching] = React.useState(false);
  const [results, setResults] = React.useState<Asset[]>([]);

  if (!beat) return null;

  const isTextCard = beat.visualType === "text_card";

  const runSearch = async () => {
    setSearching(true);
    const found = await searchClips(beat.index, query);
    setResults((prev) => [...found, ...prev]);
    setSearching(false);
  };

  const pick = (asset: Asset) => {
    // Ensure the asset exists in the beat's candidate list, then select it.
    if (!beat.candidates.some((c) => c.id === asset.id)) {
      addCandidate(beat.index, asset, true);
    } else {
      chooseAsset(beat.index, asset.id);
    }
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isTextCard ? "Edit text card" : "Choose a clip"}</DialogTitle>
          <p className="flex items-center gap-2 text-sm text-faint">
            <span className="font-mono text-xs text-accent">{fmtRange(beat.from, beat.to)}</span>
            <span className="line-clamp-1">{beat.text}</span>
          </p>
        </DialogHeader>

        {isTextCard ? (
          <Tabs defaultValue="animated">
            <TabsList>
              <TabsTrigger value="animated">Animated text</TabsTrigger>
              <TabsTrigger value="caption">Static caption</TabsTrigger>
            </TabsList>
            <TabsContent value="animated">
              <AnimatedTextTab beat={beat} aspect={jobAspect} jobId={jobId} onDone={onClose} />
            </TabsContent>
            <TabsContent value="caption">
              <TextCardEditor beat={beat} onDone={onClose} />
            </TabsContent>
          </Tabs>
        ) : (
          <Tabs defaultValue="suggested">
            <TabsList>
              <TabsTrigger value="suggested">Suggested</TabsTrigger>
              <TabsTrigger value="search">Search</TabsTrigger>
              <TabsTrigger value="animated">Animated text</TabsTrigger>
              <TabsTrigger value="library">Your library</TabsTrigger>
            </TabsList>

            <TabsContent value="suggested">
              <div className="grid max-h-[50vh] grid-cols-3 gap-3 overflow-y-auto pr-1 sm:grid-cols-4">
                {beat.candidates.map((a) => (
                  <AssetCard
                    key={a.id}
                    asset={a}
                    selected={a.id === beat.chosenAssetId}
                    onSelect={() => pick(a)}
                  />
                ))}
              </div>
            </TabsContent>

            <TabsContent value="search">
              <form
                className="mb-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void runSearch();
                }}
              >
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search stock clips…"
                  autoFocus
                />
                <Button type="submit" variant="secondary" disabled={searching}>
                  {searching ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
                  Search
                </Button>
              </form>
              <div className="grid max-h-[42vh] grid-cols-3 gap-3 overflow-y-auto pr-1 sm:grid-cols-4">
                {results.length === 0 && !searching && (
                  <p className="col-span-full py-8 text-center text-sm text-faint">
                    Search Pexels &amp; Wikimedia for a different clip.
                  </p>
                )}
                {results.map((a) => (
                  <AssetCard
                    key={a.id}
                    asset={a}
                    selected={a.id === beat.chosenAssetId}
                    onSelect={() => pick(a)}
                  />
                ))}
              </div>
            </TabsContent>

            <TabsContent value="animated">
              <AnimatedTextTab beat={beat} aspect={jobAspect} jobId={jobId} onDone={onClose} />
            </TabsContent>

            <TabsContent value="library">
              <YourLibraryTab beat={beat} onDone={onClose} />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
