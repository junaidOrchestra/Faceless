import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type StepState = "done" | "active" | "upcoming";

const STEPS: { key: string; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "beats", label: "Beats" },
  { key: "setup", label: "Setup" },
  { key: "pick", label: "Pick clips" },
  { key: "render", label: "Render" },
];

export function Stepper({ current }: { current: string }) {
  const currentIdx = STEPS.findIndex((s) => s.key === current);
  return (
    <ol className="flex items-center gap-1 overflow-x-auto">
      {STEPS.map((step, i) => {
        const state: StepState =
          i < currentIdx ? "done" : i === currentIdx ? "active" : "upcoming";
        return (
          <li key={step.key} className="flex items-center gap-1">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "grid size-5 place-items-center rounded-full border text-[10px] font-semibold transition-colors",
                  state === "done" && "border-accent/40 bg-accent/15 text-accent",
                  state === "active" && "border-accent bg-accent text-accent-foreground",
                  state === "upcoming" && "border-hairline text-faint",
                )}
              >
                {state === "done" ? <Check className="size-3" /> : i + 1}
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-xs font-medium transition-colors",
                  state === "active" ? "text-cream" : "text-faint",
                )}
              >
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span
                className={cn(
                  "mx-1 h-px w-6 shrink-0",
                  i < currentIdx ? "bg-accent/40" : "bg-hairline",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
