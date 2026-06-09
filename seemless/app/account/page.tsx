"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, LogOut, Zap } from "lucide-react";
import { AppMenu } from "@/components/app-menu";
import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { createClient } from "@/lib/supabase/client";
import { useMe } from "@/lib/use-me";

type Txn = {
  id: number;
  delta: number;
  reason: string;
  project_id: string | null;
  created_at: string;
};

export default function AccountPage() {
  const router = useRouter();
  const { me, loading } = useMe();
  const [txns, setTxns] = React.useState<Txn[]>([]);

  React.useEffect(() => {
    fetch("/api/me/credits", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { transactions: [] }))
      .then((d) => setTxns(d.transactions ?? []))
      .catch(() => setTxns([]));
  }, []);

  async function signOut() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppMenu />
          <Link href="/" className="shrink-0">
            <Brand size="sm" />
          </Link>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={signOut}>
            <LogOut className="size-4" />
            Sign out
          </Button>
        </div>
      </header>

      <Link
        href="/projects"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-faint hover:text-cream"
      >
        <ArrowLeft className="size-4" />
        Your projects
      </Link>

      <h1 className="mb-6 font-heading text-3xl font-bold text-cream">Account</h1>

      {loading && <p className="text-faint">Loading…</p>}

      {me && (
        <div className="space-y-6">
          <section className="panel space-y-4 p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm text-faint">Signed in as</p>
                <p className="text-lg font-medium text-cream">{me.email ?? me.id}</p>
              </div>
              <Badge>{me.tier_info.label} plan</Badge>
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Credits" value={String(me.credits)} accent />
              <Stat label="Monthly grant" value={String(me.tier_info.monthly_credits)} />
              <Stat label="Max length" value={`${me.tier_info.max_video_seconds}s`} />
              <Stat
                label="Max quality"
                value={`${me.tier_info.max_resolution_height}p`}
              />
            </div>

            <div className="flex flex-wrap items-center gap-3 pt-2">
              <Button variant="primary" disabled title="Billing coming soon">
                <Zap className="size-4" />
                Upgrade plan
              </Button>
              <span className="text-xs text-faint">
                {me.tier_info.watermark
                  ? "Free renders include a watermark."
                  : "Watermark-free renders included."}
              </span>
            </div>
          </section>

          <section className="panel p-6">
            <h2 className="mb-4 font-heading text-lg font-semibold text-cream">
              Credit history
            </h2>
            {txns.length === 0 ? (
              <p className="text-sm text-faint">No transactions yet.</p>
            ) : (
              <ul className="divide-y divide-hairline/60">
                {txns.map((t) => (
                  <li key={t.id} className="flex items-center justify-between py-2.5 text-sm">
                    <div>
                      <span className="capitalize text-cream">{t.reason}</span>
                      {t.project_id && (
                        <span className="ml-2 font-mono text-xs text-faint">
                          {t.project_id.slice(0, 8)}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span
                        className={
                          t.delta >= 0 ? "font-mono text-accent" : "font-mono text-faint"
                        }
                      >
                        {t.delta >= 0 ? `+${t.delta}` : t.delta}
                      </span>
                      <time className="text-xs text-faint/70">
                        {new Date(t.created_at).toLocaleDateString()}
                      </time>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function Stat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-canvas px-3 py-2.5">
      <p className="text-xs text-faint">{label}</p>
      <p className={accent ? "text-xl font-bold text-accent" : "text-xl font-semibold text-cream"}>
        {value}
      </p>
    </div>
  );
}
