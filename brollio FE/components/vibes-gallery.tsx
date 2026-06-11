import { Play } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { VIBES } from "@/lib/vibes";
import { cn } from "@/lib/utils";

/**
 * The most visual block on the page: a shelf of vibe theme cards. Each card is a
 * slowly drifting gradient with a light sheen sweep — an asset-free stand-in for
 * a looping footage preview. To swap in real video later, drop a muted, looping
 * <video> as the first child of the card and keep the overlay/label markup.
 */
export function VibesGallery() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {VIBES.map((vibe, i) => (
        <Reveal key={vibe.id} delay={(i % 4) * 70}>
          <div className="group relative aspect-[4/5] overflow-hidden rounded-xl border border-hairline">
            {/* Drifting gradient "footage" */}
            <div
              className={cn(
                "absolute inset-0 bg-gradient-to-br bg-[length:200%_200%] animate-gradient-pan transition-transform duration-700 group-hover:scale-110",
                vibe.gradient,
              )}
            />
            {/* Legibility scrim */}
            <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
            {/* Diagonal light sweep, like a clip catching light */}
            <div className="pointer-events-none absolute inset-0 overflow-hidden">
              <div className="absolute inset-y-0 -left-1/3 w-1/3 bg-white/10 blur-md animate-sheen" />
            </div>

            {/* Play affordance (sells "preview") */}
            <span className="absolute right-3 top-3 grid size-8 place-items-center rounded-full bg-black/30 text-white backdrop-blur-sm transition-transform duration-300 group-hover:scale-110">
              <Play className="size-3.5 fill-current" />
            </span>

            {/* Icon + labels */}
            <div className="absolute inset-x-0 bottom-0 p-3.5">
              <vibe.icon className="size-5 text-white/90" />
              <p className="mt-2 font-heading text-sm font-bold leading-tight text-white">
                {vibe.label}
              </p>
              <p className="mt-0.5 text-[11px] text-white/70">{vibe.mood}</p>
            </div>
          </div>
        </Reveal>
      ))}
    </div>
  );
}
