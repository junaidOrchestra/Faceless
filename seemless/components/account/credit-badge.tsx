"use client";

import Link from "next/link";
import { Zap } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/lib/use-me";
import { cn } from "@/lib/utils";

/**
 * Header pill showing the user's live credit balance. Turns amber and reads
 * "Upgrade" when the balance is exhausted. Links to the account page.
 */
export function CreditBadge({ className }: { className?: string }) {
  const { me, loading } = useMe();

  // Skeleton while loading keeps the header height stable (no pop-in); once
  // resolved, a guest (no account) renders nothing.
  if (loading) {
    return <Skeleton className={cn("h-[26px] w-[88px] rounded-full", className)} />;
  }
  if (!me) return null;

  const unlimited = me.tier_info.unlimited_credits === true;
  const empty = !unlimited && me.credits <= 0;

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
      title={
        unlimited
          ? `${me.tier_info.label} plan · unlimited credits`
          : `${me.tier_info.label} plan · ${me.credits} credits`
      }
    >
      <Zap className={cn("size-3.5", empty ? "text-accent" : "text-accent")} />
      {unlimited ? "Unlimited" : empty ? "Upgrade" : `${me.credits} credits`}
    </Link>
  );
}
