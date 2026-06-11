import { cn } from "@/lib/utils";

/** Brollio logo mark: an amber film-strip with a play glyph (a nod to "b-roll"). */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "relative grid place-items-center rounded-lg bg-accent text-accent-foreground shadow-[0_4px_16px_-4px_rgba(244,183,64,0.6)]",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="size-[66%]" fill="none" aria-hidden>
        <rect
          x="3.5"
          y="5"
          width="17"
          height="14"
          rx="3"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <g fill="currentColor">
          <rect x="5.6" y="7.2" width="1.7" height="1.7" rx="0.4" />
          <rect x="5.6" y="11.15" width="1.7" height="1.7" rx="0.4" />
          <rect x="5.6" y="15.1" width="1.7" height="1.7" rx="0.4" />
          <rect x="16.7" y="7.2" width="1.7" height="1.7" rx="0.4" />
          <rect x="16.7" y="11.15" width="1.7" height="1.7" rx="0.4" />
          <rect x="16.7" y="15.1" width="1.7" height="1.7" rx="0.4" />
        </g>
        <path d="M10.2 9.3v5.4l4.4-2.7-4.4-2.7Z" fill="currentColor" />
      </svg>
    </span>
  );
}

export function Brand({
  className,
  size = "md",
}: {
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const mark = size === "lg" ? "size-9" : size === "sm" ? "size-7" : "size-8";
  const text = size === "lg" ? "text-2xl" : size === "sm" ? "text-base" : "text-lg";
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark className={mark} />
      <span className={cn("font-heading font-bold tracking-tight text-cream", text)}>
        Broll<span className="text-accent">io</span>
      </span>
    </div>
  );
}
