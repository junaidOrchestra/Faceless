"use client";

import Link from "next/link";
import { Zap } from "lucide-react";
import { useMe } from "@/lib/use-me";
import { cn } from "@/lib/utils";

/**
 * Header pill showing the user's live credit balance. Turns amber and reads
 * "Upgrade" when the balance is exhausted. Links to the account page.
 */
export function CreditBadge({ className }: { className?: string }) {
  const { me, loading } = useMe();

  if (loading || !me) return null;

  const empty = me.credits <= 0;

  return (
    <Link
      href="/account"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        empty
          ? "border-accent/60 bg-accent/10 text-accent hover:bg-accent/20"
          : "border-hairline bg-panel text-cream hover:border-hairline/80",
        className,
      )}
      title={`${me.tier_info.label} plan · ${me.credits} credits`}
    >
      <Zap className={cn("size-3.5", empty ? "text-accent" : "text-accent")} />
      {empty ? "Upgrade" : `${me.credits} credits`}
    </Link>
  );
}
