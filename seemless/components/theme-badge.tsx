"use client";

import { Wand2 } from "lucide-react";
import { VIBES } from "@/lib/vibes";
import type { ContentTheme } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Compact, read-only indicator of the content theme chosen at setup: either
 * "Matches your content" (script mode) or the selected vibe (with its icon).
 * Shown on the pick-clips and render screens so the user can see what's driving
 * the visuals.
 */
export function ThemeBadge({
  theme,
  className,
}: {
  theme: ContentTheme;
  className?: string;
}) {
  if (theme.mode === "vibe") {
    const vibe = VIBES.find((v) => v.id === theme.vibe);
    const Icon = vibe?.icon ?? Wand2;
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent",
          className,
        )}
      >
        <Icon className="size-3.5" />
        {vibe?.label ?? theme.vibe}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-hairline bg-panel-raised px-2.5 py-1 text-xs font-medium text-cream",
        className,
      )}
    >
      <Wand2 className="size-3.5 text-faint" />
      Matches your content
    </span>
  );
}
