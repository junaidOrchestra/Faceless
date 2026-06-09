"use client";

import Link from "next/link";
import { MousePointerClick, Shield, Sparkles, Upload } from "lucide-react";
import { AppMenu } from "@/components/app-menu";
import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";

const STEPS = [
  {
    icon: Upload,
    title: "Add your narration",
    body: "Upload or record a voiceover — audio or video. We transcribe it and break it into short spoken beats.",
  },
  {
    icon: MousePointerClick,
    title: "Pick a visual per beat",
    body: "For each beat we suggest matching stock clips. Review, swap, or upload your own — you stay in control.",
  },
  {
    icon: Sparkles,
    title: "Render the video",
    body: "We stitch the clips to your narration, burn in captions, and export a finished faceless video.",
  },
];

export default function AboutPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-10 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppMenu />
          <Link href="/" className="shrink-0">
            <Brand size="sm" />
          </Link>
        </div>
        <ThemeToggle />
      </header>

      <section className="mb-12 text-center">
        <h1 className="font-heading text-3xl font-bold leading-tight text-cream sm:text-4xl">
          Turn narration into a{" "}
          <span className="text-accent">faceless video</span>, beat by beat.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-balance text-faint">
          Brollio is a studio for creators who tell stories with their voice.
          Instead of hunting for b-roll and editing a timeline by hand, you bring
          the narration and we handle the visuals — one spoken beat at a time.
        </p>
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button variant="primary" asChild>
            <Link href="/">
              <Sparkles className="size-4" />
              Make a video
            </Link>
          </Button>
          <Button variant="secondary" asChild>
            <Link href="/pricing">See pricing</Link>
          </Button>
        </div>
      </section>

      <section className="mb-12">
        <h2 className="mb-4 font-heading text-xl font-bold text-cream">How it works</h2>
        <ol className="space-y-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="panel flex items-start gap-4 p-5">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 font-heading font-bold text-accent">
                {i + 1}
              </span>
              <div>
                <div className="flex items-center gap-2">
                  <s.icon className="size-4 text-accent" />
                  <p className="font-medium text-cream">{s.title}</p>
                </div>
                <p className="mt-1 text-sm text-faint">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="panel flex items-start gap-4 p-6">
        <Shield className="mt-0.5 size-6 shrink-0 text-accent" />
        <div>
          <h2 className="font-heading text-lg font-bold text-cream">
            Your audio stays private
          </h2>
          <p className="mt-1 text-sm text-faint">
            Narration is processed only to build your video and is tied to your
            account — never shared or used to train anything. Finished videos are
            yours to download.
          </p>
        </div>
      </section>

      <footer className="pt-10 text-center text-xs text-faint/70">
        Brollio — powered by the Brollio orchestrator.
      </footer>
    </main>
  );
}
