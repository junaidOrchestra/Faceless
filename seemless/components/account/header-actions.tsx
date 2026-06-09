"use client";

import Link from "next/link";
import { CreditBadge } from "@/components/account/credit-badge";
import { useMe } from "@/lib/use-me";

/**
 * Auth-aware header controls: a signed-in user sees their credit balance and a
 * link to their projects; a guest sees a sign-in link.
 */
export function HeaderActions() {
  const { me, loading } = useMe();

  if (loading) return null;

  if (!me) {
    return (
      <Link
        href="/login"
        className="rounded-full border border-hairline bg-panel px-3 py-1 text-xs font-medium text-cream hover:border-hairline/80"
      >
        Sign in
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <CreditBadge />
      <Link
        href="/projects"
        className="rounded-full border border-hairline bg-panel px-3 py-1 text-xs font-medium text-cream hover:border-hairline/80"
      >
        Projects
      </Link>
    </div>
  );
}
