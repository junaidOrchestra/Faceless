import { Captions, Check, Wand2 } from "lucide-react";
import { cn } from "@/lib/utils";

// A faux "Pick Clips" panel that sells the beat-by-beat concept without any
// real screenshots. Each beat shows a spoken line + a matched clip thumbnail.
const BEATS = [
  { line: "It started with a simple idea…", tone: "from-amber-400/80 to-orange-500/70", chosen: true },
  { line: "a notebook and a lot of coffee.", tone: "from-sky-400/80 to-indigo-500/70", chosen: true },
  { line: "Months later, it shipped.", tone: "from-emerald-400/80 to-teal-500/70", chosen: false },
];

export function HeroPreview() {
  return (
    <div className="relative">
      {/* Glow behind the panel */}
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-6 -z-10 rounded-[2rem] bg-accent/10 blur-3xl"
      />

      <div className="panel overflow-hidden rounded-2xl">
        {/* Window chrome */}
        <div className="flex items-center gap-2 border-b border-hairline bg-panel-raised/60 px-4 py-3">
          <span className="size-2.5 rounded-full bg-destructive/70" />
          <span className="size-2.5 rounded-full bg-accent/70" />
          <span className="size-2.5 rounded-full bg-emerald-400/70" />
          <span className="ml-2 font-mono text-xs text-faint">brollio · pick clips</span>
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
            <Wand2 className="size-3" /> auto-matched
          </span>
        </div>

        {/* Narration waveform */}
        <div className="flex items-center gap-2 border-b border-hairline px-4 py-3">
          <Captions className="size-4 shrink-0 text-faint" />
          <div className="flex h-7 flex-1 items-center gap-[3px] overflow-hidden">
            {WAVE.map((h, i) => (
              <span
                key={i}
                className="w-[3px] shrink-0 rounded-full bg-accent/60"
                style={{ height: `${h}%` }}
              />
            ))}
          </div>
        </div>

        {/* Beats */}
        <div className="space-y-2.5 p-4">
          {BEATS.map((beat, i) => (
            <div
              key={i}
              className="flex items-center gap-3 rounded-xl border border-hairline bg-panel-raised/40 p-2.5"
            >
              <div
                className={cn(
                  "relative grid h-12 w-20 shrink-0 place-items-center overflow-hidden rounded-lg bg-gradient-to-br",
                  beat.tone,
                )}
              >
                <span className="absolute inset-0 bg-black/10" />
                <span className="relative font-mono text-[10px] font-semibold text-white/90">
                  clip {i + 1}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-cream">{beat.line}</p>
                <p className="mt-0.5 text-[11px] text-faint">Beat {i + 1} · 3.2s</p>
              </div>
              {beat.chosen ? (
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-accent text-accent-foreground">
                  <Check className="size-3.5" />
                </span>
              ) : (
                <span className="size-6 shrink-0 rounded-full border-2 border-dashed border-hairline" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Floating "rendered" pill */}
      <div className="absolute -bottom-5 -right-3 hidden animate-float rounded-xl border border-hairline bg-panel px-4 py-3 shadow-xl sm:block">
        <p className="text-xs font-semibold text-cream">Rendered in 1080p</p>
        <p className="text-[11px] text-faint">captions burned in ✓</p>
      </div>
    </div>
  );
}

// Pseudo-random but stable waveform heights.
const WAVE = [
  30, 55, 40, 70, 90, 60, 45, 80, 65, 35, 50, 75, 95, 55, 40, 60, 85, 45, 30, 70,
  55, 80, 60, 40, 90, 50, 35, 65, 75, 45, 55, 85, 40, 60, 70, 30, 50, 80, 45, 65,
  90, 55, 35, 70, 60, 40, 75, 50, 85, 45,
];
