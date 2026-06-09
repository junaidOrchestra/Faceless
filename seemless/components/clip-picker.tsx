"use client";

import * as React from "react";
import { Check, Loader2, Play, Search, UploadCloud, Video } from "lucide-react";
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
import { searchClips, uploadOwnClip } from "@/lib/api";
import { useEditorStore } from "@/lib/store";
import type { Asset, Beat } from "@/lib/types";
import { cn, fmtRange } from "@/lib/utils";

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
  // Without a still-image poster (e.g. the user's own uploaded footage), append
  // a media fragment so the browser loads and paints the frame at 0.1s as the
  // static thumbnail instead of showing a black tile.
  const videoSrc =
    isVideo && !posterUrl ? `${asset.mediaUrl}#t=0.1` : asset.mediaUrl;

  const play = () => {
    if (!isVideo) return;
    setActive(true);
  };
  const stop = () => {
    if (!isVideo) return;
    const v = videoRef.current;
    if (v) {
      v.pause();
      v.currentTime = 0;
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
        />
      ) : posterUrl ? (
        <img src={posterUrl} alt="" className="size-full object-cover" loading="lazy" />
      ) : isVideo ? (
        <div className="grid size-full place-items-center text-faint">
          <Video className="size-6" />
        </div>
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
          <TextCardEditor beat={beat} onDone={onClose} />
        ) : (
          <Tabs defaultValue="suggested">
            <TabsList>
              <TabsTrigger value="suggested">Suggested</TabsTrigger>
              <TabsTrigger value="search">Search</TabsTrigger>
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

            <TabsContent value="library">
              <YourLibraryTab beat={beat} onDone={onClose} />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}
