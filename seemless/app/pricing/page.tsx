"use client";

import Link from "next/link";
import { Check, Clock, Sparkles, Zap } from "lucide-react";
import { AppMenu } from "@/components/app-menu";
import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useMe } from "@/lib/use-me";
import { cn } from "@/lib/utils";

// Mirrors orchestrator/app/tiers.py TIER_CONFIG. Kept in sync manually; this is
// an informational page, the orchestrator remains the source of truth for
// enforcement.
const SECONDS_PER_CREDIT = 15;

type Plan = {
  name: string;
  label: string;
  blurb: string;
  monthlyCredits: number;
  maxVideoSeconds: number;
  maxResolution: string;
  watermark: boolean;
  maxProjects: number;
  maxConcurrentJobs: number;
  highlight?: boolean;
  perks: string[];
};

const PLANS: Plan[] = [
  {
    name: "free",
    label: "Free",
    blurb: "Try it out — monthly credits, no card required.",
    monthlyCredits: 30,
    maxVideoSeconds: 60,
    maxResolution: "720p",
    watermark: true,
    maxProjects: 5,
    maxConcurrentJobs: 1,
    perks: ["Stock clips", "Auto captions"],
  },
  {
    name: "individual",
    label: "Individual",
    blurb: "For regular creators who publish often.",
    monthlyCredits: 300,
    maxVideoSeconds: 300,
    maxResolution: "1080p",
    watermark: false,
    maxProjects: 50,
    maxConcurrentJobs: 3,
    highlight: true,
    perks: ["Stock clips", "Auto captions", "No watermark", "HD export"],
  },
  {
    name: "professional",
    label: "Professional",
    blurb: "For teams and high-volume production.",
    monthlyCredits: 1500,
    maxVideoSeconds: 900,
    maxResolution: "4K",
    watermark: false,
    maxProjects: 0,
    maxConcurrentJobs: 10,
    perks: [
      "Stock clips",
      "Auto captions",
      "No watermark",
      "HD export",
      "4K export",
      "Priority rendering",
    ],
  },
];

function fmtLen(seconds: number): string {
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds}s`;
}

export default function PricingPage() {
  const { me } = useMe();

  return (
    <main className="mx-auto max-w-5xl px-6 py-8">
      <header className="mb-10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppMenu />
          <Link href="/" className="shrink-0">
            <Brand size="sm" />
          </Link>
        </div>
        <ThemeToggle />
      </header>

      <div className="mx-auto mb-10 max-w-2xl text-center">
        <h1 className="font-heading text-3xl font-bold text-cream sm:text-4xl">
          Pricing & credits
        </h1>
        <p className="mt-3 text-balance text-faint">
          Every render spends credits based on the final video length. Each plan
          grants a monthly batch of credits — unused work never blocks you from
          reviewing clips, you only spend when you render.
        </p>
      </div>

      {/* How credits work */}
      <section className="panel mb-10 grid grid-cols-1 gap-4 p-6 sm:grid-cols-3">
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent">
            <Zap className="size-5" />
          </span>
          <div>
            <p className="text-sm font-semibold text-cream">1 credit ≈ {SECONDS_PER_CREDIT}s</p>
            <p className="text-xs text-faint">
              Render cost = length ÷ {SECONDS_PER_CREDIT}s, rounded up. A 45s video
              costs 3 credits.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent">
            <Clock className="size-5" />
          </span>
          <div>
            <p className="text-sm font-semibold text-cream">Charged at render</p>
            <p className="text-xs text-faint">
              Uploading, transcribing and picking clips is free. Credits are only
              spent when you make the final video.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent">
            <Sparkles className="size-5" />
          </span>
          <div>
            <p className="text-sm font-semibold text-cream">Auto-refunded on failure</p>
            <p className="text-xs text-faint">
              If a render fails, the credits for that job are returned to your
              balance automatically.
            </p>
          </div>
        </div>
      </section>

      {/* Plans */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {PLANS.map((plan) => {
          const current = me?.tier === plan.name;
          return (
            <div
              key={plan.name}
              className={cn(
                "panel relative flex flex-col gap-4 p-6",
                plan.highlight && "ring-1 ring-accent/50",
              )}
            >
              {plan.highlight && (
                <span className="absolute -top-2.5 left-6 rounded-full bg-accent px-2.5 py-0.5 text-[11px] font-semibold text-accent-foreground">
                  Most popular
                </span>
              )}
              <div>
                <div className="flex items-center justify-between">
                  <h2 className="font-heading text-xl font-bold text-cream">
                    {plan.label}
                  </h2>
                  {current && (
                    <span className="rounded-full border border-accent/60 bg-accent/10 px-2 py-0.5 text-[11px] font-medium text-accent">
                      Your plan
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-faint">{plan.blurb}</p>
              </div>

              <div className="flex items-baseline gap-1.5">
                <span className="font-heading text-3xl font-bold text-cream">
                  {plan.monthlyCredits}
                </span>
                <span className="text-sm text-faint">credits / month</span>
              </div>

              <dl className="space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <dt className="text-faint">Max length</dt>
                  <dd className="text-cream">{fmtLen(plan.maxVideoSeconds)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-faint">Max resolution</dt>
                  <dd className="text-cream">{plan.maxResolution}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-faint">Projects</dt>
                  <dd className="text-cream">
                    {plan.maxProjects === 0 ? "Unlimited" : `Up to ${plan.maxProjects}`}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-faint">Concurrent renders</dt>
                  <dd className="text-cream">
                    {plan.maxConcurrentJobs === 0
                      ? "Unlimited"
                      : `${plan.maxConcurrentJobs} at a time`}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-faint">Watermark</dt>
                  <dd className="text-cream">{plan.watermark ? "Yes" : "No"}</dd>
                </div>
              </dl>

              <ul className="space-y-1.5">
                {plan.perks.map((perk) => (
                  <li key={perk} className="flex items-center gap-2 text-xs text-cream">
                    <Check className="size-3.5 shrink-0 text-accent" />
                    {perk}
                  </li>
                ))}
              </ul>

              <div className="mt-auto pt-2">
                <Button
                  variant={plan.highlight ? "primary" : "secondary"}
                  className="w-full"
                  asChild
                >
                  <Link href="/account">
                    {current ? "Manage plan" : `Choose ${plan.label}`}
                  </Link>
                </Button>
              </div>
            </div>
          );
        })}
      </section>

      <p className="mt-8 text-center text-xs text-faint/70">
        Plan changes and billing are managed from your account.
      </p>
    </main>
  );
}
