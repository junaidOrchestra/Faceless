"use client";

import { Captions, FileText, Gauge, Loader2, Palette, Ratio, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ASPECTS, QUALITIES, useEditorStore } from "@/lib/store";
import type { VideoJob } from "@/lib/types";
import { VIBES } from "@/lib/vibes";
import { cn } from "@/lib/utils";

/**
 * Output setup, offered as soon as the upload returns — it doesn't depend on
 * the transcript, so the user fills it while transcription runs. Committing it
 * (POST /prepare) starts the clip search: immediately if beats are ready, or
 * automatically once transcription finishes if it's still running.
 */
export function SetupCard({
  job,
  transcribing = false,
}: {
  job: VideoJob;
  transcribing?: boolean;
}) {
  const updateSettings = useEditorStore((s) => s.updateSettings);
  const prepare = useEditorStore((s) => s.prepare);
  const preparing = useEditorStore((s) => s.preparing);

  const vibeMode = job.theme.mode === "vibe";
  const selectedVibe = job.theme.mode === "vibe" ? job.theme.vibe : null;

  return (
    <div className="panel mb-4 animate-fade-rise overflow-hidden">
      <div className="border-b border-hairline bg-panel-raised/40 px-4 py-3">
        <h3 className="flex items-center gap-2 font-heading text-base font-semibold text-cream">
          <Sparkles className="size-4 text-accent" />
          Set up your output
        </h3>
        <p className="mt-0.5 text-xs text-faint">
          {transcribing
            ? "We're transcribing your narration now — set the output while you wait and we'll start finding clips automatically."
            : "Choose the output shape — we'll fetch clips that match before you pick."}
        </p>
      </div>

      <div className="space-y-5 p-4">
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-faint">
            <Palette className="size-3.5" /> Content theme
          </p>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => updateSettings({ theme: { mode: "script" } })}
              className={cn(
                "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-left transition-all",
                !vibeMode
                  ? "border-accent bg-accent/10"
                  : "border-hairline hover:border-hairline/80",
              )}
            >
              <FileText
                className={cn("mt-0.5 size-4 shrink-0", !vibeMode ? "text-accent" : "text-faint")}
              />
              <span>
                <span
                  className={cn(
                    "block text-sm font-medium",
                    !vibeMode ? "text-accent" : "text-cream",
                  )}
                >
                  Match my script
                </span>
                <span className="text-[11px] text-faint">Visuals follow what you say.</span>
              </span>
            </button>
            <button
              type="button"
              onClick={() =>
                updateSettings({
                  theme: { mode: "vibe", vibe: selectedVibe ?? VIBES[0].id },
                })
              }
              className={cn(
                "flex items-start gap-2 rounded-lg border px-3 py-2.5 text-left transition-all",
                vibeMode
                  ? "border-accent bg-accent/10"
                  : "border-hairline hover:border-hairline/80",
              )}
            >
              <Palette
                className={cn("mt-0.5 size-4 shrink-0", vibeMode ? "text-accent" : "text-faint")}
              />
              <span>
                <span
                  className={cn(
                    "block text-sm font-medium",
                    vibeMode ? "text-accent" : "text-cream",
                  )}
                >
                  Choose a vibe
                </span>
                <span className="text-[11px] text-faint">One ambient look throughout.</span>
              </span>
            </button>
          </div>

          {vibeMode && (
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {VIBES.map((v) => {
                const active = selectedVibe === v.id;
                return (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => updateSettings({ theme: { mode: "vibe", vibe: v.id } })}
                    title={v.mood}
                    className={cn(
                      "group relative overflow-hidden rounded-xl border text-left transition-all",
                      active
                        ? "border-accent ring-2 ring-accent/50"
                        : "border-hairline hover:border-accent/40",
                    )}
                  >
                    <div
                      className={cn(
                        "flex h-16 items-end bg-gradient-to-br p-2",
                        v.gradient,
                      )}
                    >
                      <v.icon className="size-5 text-white/90 drop-shadow" />
                    </div>
                    <div className="bg-panel px-2 py-1.5">
                      <p className="truncate text-[11px] font-medium leading-tight text-cream">
                        {v.label}
                      </p>
                      <p className="truncate text-[10px] leading-tight text-faint">{v.mood}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-faint">
            <Ratio className="size-3.5" /> Aspect ratio
          </p>
          <div className="flex gap-2">
            {ASPECTS.map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => updateSettings({ aspect: a })}
                className={cn(
                  "flex-1 rounded-lg border px-2 py-2 font-mono text-xs transition-all",
                  job.aspect === a
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-hairline text-faint hover:border-hairline/80 hover:text-cream",
                )}
              >
                {a}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-faint">
            <Gauge className="size-3.5" /> Quality
          </p>
          <div className="flex gap-2">
            {QUALITIES.map((q) => (
              <button
                key={q.value}
                type="button"
                onClick={() => updateSettings({ quality: q.value })}
                className={cn(
                  "flex-1 rounded-lg border px-3 py-2 text-left transition-all",
                  job.quality === q.value
                    ? "border-accent bg-accent/10"
                    : "border-hairline hover:border-hairline/80",
                )}
              >
                <span
                  className={cn(
                    "block text-sm font-medium",
                    job.quality === q.value ? "text-accent" : "text-cream",
                  )}
                >
                  {q.label}
                </span>
                <span className="text-[11px] text-faint">{q.hint}</span>
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm text-cream">
            <Captions className="size-4 text-faint" />
            Burn captions
          </span>
          <Switch
            checked={job.captions}
            onCheckedChange={(v) => updateSettings({ captions: v })}
          />
        </label>

        <Button
          variant="primary"
          className="w-full"
          disabled={preparing}
          onClick={() => void prepare()}
        >
          {preparing ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Sparkles className="size-4" />
              {transcribing ? "Save & find clips" : "Find clips"}
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
