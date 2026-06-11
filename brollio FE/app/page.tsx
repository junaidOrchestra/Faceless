import Link from "next/link";
import {
  AlignLeft,
  ArrowRight,
  Captions,
  Check,
  Clock,
  Image as ImageIcon,
  Languages,
  Layers,
  MousePointerClick,
  Palette,
  RefreshCw,
  Shield,
  Sparkles,
  Upload,
  Wand2,
  Zap,
} from "lucide-react";
import { HeroPreview } from "@/components/hero-preview";
import { Reveal } from "@/components/reveal";
import { SiteFooter } from "@/components/site-footer";
import { SiteNav } from "@/components/site-nav";
import { VibesGallery } from "@/components/vibes-gallery";
import { APP_URL, cn } from "@/lib/utils";

const STEPS = [
  {
    icon: Upload,
    title: "Add your narration",
    body: "Upload or record audio or video. We pull the narration, transcribe it, and split it into short spoken beats automatically.",
  },
  {
    icon: MousePointerClick,
    title: "Pick a visual per beat",
    body: "For each beat we suggest matching stock clips. Review, swap, or drop in your own — you stay in control.",
  },
  {
    icon: Sparkles,
    title: "Render the video",
    body: "We stitch the clips to your narration, burn in captions, and export a finished faceless video.",
  },
];

const FEATURES = [
  {
    icon: Wand2,
    title: "AI beat detection",
    body: "Your script is broken into spoken moments, so visuals change exactly when your story does.",
  },
  {
    icon: ImageIcon,
    title: "Smart clip matching",
    body: "Every beat gets relevant stock footage suggestions you can accept or swap in one click.",
  },
  {
    icon: Captions,
    title: "Auto captions",
    body: "Word-accurate subtitles are generated from your audio and burned into the export.",
  },
  {
    icon: Layers,
    title: "Bring your own footage",
    body: "Prefer a specific shot? Upload your own clips and mix them with stock per beat.",
  },
  {
    icon: Palette,
    title: "Vibe themes",
    body: "Pick a visual vibe and let Brollio assemble a cohesive look across the whole video.",
  },
  {
    icon: Languages,
    title: "Shorts & widescreen",
    body: "Export 9:16 for Reels, Shorts and TikTok, or 16:9 for YouTube — same project.",
  },
];

const PLANS = [
  {
    name: "Free",
    blurb: "Try it out — monthly credits, no card required.",
    credits: 30,
    perks: ["60s max length", "720p export", "Up to 5 projects", "Stock clips & captions"],
    cta: "Start free",
    highlight: false,
  },
  {
    name: "Individual",
    blurb: "For regular creators who publish often.",
    credits: 300,
    perks: ["5 min max length", "1080p export", "No watermark", "Up to 50 projects"],
    cta: "Choose Individual",
    highlight: true,
  },
  {
    name: "Professional",
    blurb: "For teams and high-volume production.",
    credits: 1500,
    perks: ["15 min max length", "4K export", "Unlimited projects", "Priority rendering"],
    cta: "Choose Professional",
    highlight: false,
  },
];

const FAQS = [
  {
    q: "What exactly is a faceless video?",
    a: "It's a video driven entirely by your voiceover and visuals — stock clips, b-roll, and captions — without ever showing your face or filming yourself. Perfect for storytelling, explainers, and social shorts.",
  },
  {
    q: "Do I need any editing experience?",
    a: "No. You bring the narration; Brollio handles transcription, beat splitting, clip suggestions, captions, and rendering. You just review each beat and hit render.",
  },
  {
    q: "Where do the clips come from?",
    a: "We suggest relevant footage from stock libraries for each spoken beat. You can swap any suggestion or upload your own clips when you want a specific shot.",
  },
  {
    q: "How do credits work?",
    a: "Uploading, transcribing, and picking clips is free. You only spend credits when you render the final video — roughly one credit per 15 seconds. Failed renders are refunded automatically.",
  },
  {
    q: "Is my audio private?",
    a: "Yes. Narration is processed only to build your video and is tied to your account — never shared or used to train anything. Finished videos are yours to download.",
  },
  {
    q: "Which aspect ratios are supported?",
    a: "Both 9:16 (Reels, Shorts, TikTok) and 16:9 (YouTube and widescreen). You choose the format before you render.",
  },
];

export default function HomePage() {
  return (
    <div id="top" className="min-h-screen">
      <SiteNav />

      {/* ---------------------------------------------------------------- HERO */}
      <section className="relative overflow-hidden">
        <div className="grid-bg pointer-events-none absolute inset-0 -z-10 opacity-60 [mask-image:radial-gradient(60rem_40rem_at_50%_0%,black,transparent)]" />
        <div className="mx-auto grid max-w-content items-center gap-12 px-4 pb-20 pt-16 sm:px-6 lg:grid-cols-2 lg:gap-8 lg:px-8 lg:pb-28 lg:pt-24">
          <div>
            <Reveal>
              <span className="chip">
                <Sparkles className="size-3.5 text-accent" />
                Narration in, faceless video out
              </span>
            </Reveal>
            <Reveal delay={60}>
              <h1 className="mt-5 font-heading text-4xl font-extrabold leading-[1.05] tracking-tight text-cream sm:text-5xl lg:text-6xl">
                Turn your narration into{" "}
                <span className="text-gradient">faceless videos</span>, beat by beat.
              </h1>
            </Reveal>
            <Reveal delay={120}>
              <p className="mt-5 max-w-xl text-balance text-lg leading-relaxed text-faint">
                Brollio listens to your audio or video and adds relevant b-roll to
                every moment — or sets your whole video against a beautiful vibe.
                Match your message, or set the mood. No more scrubbing stock sites.
              </p>
            </Reveal>
            <Reveal delay={180}>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <a href={`${APP_URL}/signup`} className="btn-primary btn-lg">
                  Start free
                  <ArrowRight className="size-4" />
                </a>
                <a href="#how" className="btn-secondary btn-lg">
                  See how it works
                </a>
              </div>
            </Reveal>
            <Reveal delay={240}>
              <ul className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-faint">
                {["No camera needed", "Free monthly credits", "No card to start"].map(
                  (item) => (
                    <li key={item} className="inline-flex items-center gap-1.5">
                      <Check className="size-4 text-accent" />
                      {item}
                    </li>
                  ),
                )}
              </ul>
            </Reveal>
          </div>

          <Reveal delay={160} className="lg:pl-6">
            <HeroPreview />
          </Reveal>
        </div>
      </section>

      {/* ----------------------------------------------------------- TRUST BAR */}
      <section className="border-y border-hairline bg-panel/40">
        <div className="mx-auto grid max-w-content grid-cols-2 gap-6 px-4 py-8 sm:px-6 md:grid-cols-4 lg:px-8">
          {[
            { stat: "3 steps", label: "Audio or video in" },
            { stat: "9:16 & 16:9", label: "Every platform" },
            { stat: "Auto", label: "Captions & b-roll" },
            { stat: "1080p / 4K", label: "Crisp exports" },
          ].map((item) => (
            <div key={item.label} className="text-center">
              <p className="font-heading text-2xl font-bold text-cream">{item.stat}</p>
              <p className="mt-1 text-sm text-faint">{item.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------- HOW IT WORKS */}
      <section id="how" className="mx-auto max-w-content px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <Reveal className="mx-auto max-w-2xl text-center">
          <span className="chip">
            <Layers className="size-3.5 text-accent" />
            How it works
          </span>
          <h2 className="mt-4 font-heading text-3xl font-bold text-cream sm:text-4xl">
            From narration to finished video in three steps
          </h2>
          <p className="mt-3 text-balance text-faint">
            No timeline to wrangle. Brollio turns the words you speak into the
            visuals your story needs.
          </p>
        </Reveal>

        <div className="mt-14 grid gap-5 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <Reveal key={step.title} delay={i * 90}>
              <div className="panel group relative h-full p-6 transition-transform duration-300 hover:-translate-y-1">
                <span className="absolute right-5 top-5 font-heading text-5xl font-extrabold text-accent/10">
                  {i + 1}
                </span>
                <span className="grid size-11 place-items-center rounded-xl bg-accent/10 text-accent">
                  <step.icon className="size-5" />
                </span>
                <h3 className="mt-5 font-heading text-lg font-bold text-cream">
                  {step.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-faint">{step.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ----------------------------------------------------- TWO WAYS TO CREATE */}
      <section className="border-y border-hairline bg-panel/30 py-20 lg:py-28">
        <div className="mx-auto max-w-content px-4 sm:px-6 lg:px-8">
          <Reveal className="mx-auto max-w-2xl text-center">
            <span className="chip">Two ways to create</span>
            <h2 className="mt-4 font-heading text-3xl font-bold text-cream sm:text-4xl">
              Match your message, or set the mood
            </h2>
            <p className="mt-3 text-balance text-faint">
              The same narration, two very different looks. Choose per project —
              switch any time.
            </p>
          </Reveal>

          <div className="mx-auto mt-12 grid max-w-4xl gap-5 md:grid-cols-2">
            <Reveal>
              <div className="panel h-full p-7 transition-transform duration-300 hover:-translate-y-1">
                <span className="grid size-11 place-items-center rounded-xl bg-accent/10 text-accent">
                  <AlignLeft className="size-5" />
                </span>
                <h3 className="mt-5 font-heading text-xl font-bold text-cream">
                  Match my script
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-faint">
                  Brollio illustrates your narration moment by moment with b-roll
                  that fits exactly what you&apos;re saying. Best for explainers,
                  education, and storytelling.
                </p>
              </div>
            </Reveal>
            <Reveal delay={90}>
              <div className="panel relative h-full overflow-hidden p-7 ring-1 ring-accent/30 transition-transform duration-300 hover:-translate-y-1">
                <div
                  aria-hidden
                  className="pointer-events-none absolute -right-10 -top-10 size-32 rounded-full bg-accent/10 blur-2xl"
                />
                <span className="grid size-11 place-items-center rounded-xl bg-accent/10 text-accent">
                  <Palette className="size-5" />
                </span>
                <h3 className="mt-5 font-heading text-xl font-bold text-cream">
                  Pick a vibe
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-faint">
                  Don&apos;t need literal clips? Set your content against a stunning
                  theme — and Brollio handles the rest. Best for mood-driven
                  content where atmosphere is the point.
                </p>
                <a
                  href="#vibes"
                  className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-accent hover:text-accent-hover"
                >
                  Explore vibes
                  <ArrowRight className="size-4" />
                </a>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- VIBES */}
      <section id="vibes" className="mx-auto max-w-content px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <Reveal className="mx-auto max-w-2xl text-center">
          <span className="chip">
            <Palette className="size-3.5 text-accent" />
            Vibe mode
          </span>
          <h2 className="mt-4 font-heading text-3xl font-bold text-cream sm:text-4xl">
            Not every video needs literal b-roll. Some just need a vibe.
          </h2>
          <p className="mt-3 text-balance text-faint">
            Sometimes you don&apos;t want clips that explain — you want atmosphere.
            Pick a vibe and Brollio sets your audio or video against beautiful,
            mood-matched footage that runs the length of your piece. One tap,
            instant cinematic backdrop.
          </p>
        </Reveal>

        <div className="mt-12">
          <VibesGallery />
        </div>

        <Reveal className="mt-8 text-center">
          <p className="text-sm text-faint">
            <span className="text-cream">✨ New vibes added all the time.</span>{" "}
            Perfect for calm &amp; meditation content, lofi and music, motivational
            videos, podcast clips, faceless channels, and aesthetic reels — anytime
            the mood matters more than literal visuals.
          </p>
          <a href={`${APP_URL}/signup`} className="btn-primary btn-lg mt-7">
            Try a vibe free
            <ArrowRight className="size-4" />
          </a>
        </Reveal>
      </section>

      {/* ----------------------------------------------------------- FEATURES */}
      <section
        id="features"
        className="border-y border-hairline bg-panel/30 py-20 lg:py-28"
      >
        <div className="mx-auto max-w-content px-4 sm:px-6 lg:px-8">
          <Reveal className="mx-auto max-w-2xl text-center">
            <span className="chip">
              <Sparkles className="size-3.5 text-accent" />
              Everything included
            </span>
            <h2 className="mt-4 font-heading text-3xl font-bold text-cream sm:text-4xl">
              A full studio, minus the busywork
            </h2>
            <p className="mt-3 text-balance text-faint">
              The tedious parts of faceless video — sourcing b-roll, syncing
              captions, exporting per platform — are handled for you.
            </p>
          </Reveal>

          <div className="mt-14 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature, i) => (
              <Reveal key={feature.title} delay={(i % 3) * 80}>
                <div className="panel h-full p-6 transition-transform duration-300 hover:-translate-y-1">
                  <span className="grid size-11 place-items-center rounded-xl bg-accent/10 text-accent">
                    <feature.icon className="size-5" />
                  </span>
                  <h3 className="mt-5 font-heading text-lg font-bold text-cream">
                    {feature.title}
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-faint">
                    {feature.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ PRICING */}
      <section id="pricing" className="mx-auto max-w-content px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <Reveal className="mx-auto max-w-2xl text-center">
          <span className="chip">
            <Zap className="size-3.5 text-accent" />
            Simple credits
          </span>
          <h2 className="mt-4 font-heading text-3xl font-bold text-cream sm:text-4xl">
            Pay only when you render
          </h2>
          <p className="mt-3 text-balance text-faint">
            Every plan grants monthly credits. Reviewing clips is always free —
            you spend credits based on final video length, and failed renders are
            refunded automatically.
          </p>
        </Reveal>

        {/* Credit explainer */}
        <Reveal className="mx-auto mt-10 max-w-3xl">
          <div className="panel grid gap-4 p-6 sm:grid-cols-3">
            {[
              { icon: Zap, title: "1 credit ≈ 15s", body: "Cost = length ÷ 15s, rounded up." },
              { icon: Clock, title: "Charged at render", body: "Upload, transcribe and pick for free." },
              { icon: RefreshCw, title: "Auto-refunded", body: "Failed renders return your credits." },
            ].map((item) => (
              <div key={item.title} className="flex items-start gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/10 text-accent">
                  <item.icon className="size-5" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-cream">{item.title}</p>
                  <p className="text-xs text-faint">{item.body}</p>
                </div>
              </div>
            ))}
          </div>
        </Reveal>

        <div className="mt-12 grid gap-5 md:grid-cols-3">
          {PLANS.map((plan, i) => (
            <Reveal key={plan.name} delay={i * 90}>
              <div
                className={cn(
                  "panel relative flex h-full flex-col p-6",
                  plan.highlight && "ring-2 ring-accent/50",
                )}
              >
                {plan.highlight && (
                  <span className="absolute -top-3 left-6 rounded-full bg-accent px-3 py-1 text-[11px] font-semibold text-accent-foreground">
                    Most popular
                  </span>
                )}
                <h3 className="font-heading text-xl font-bold text-cream">{plan.name}</h3>
                <p className="mt-1 min-h-[2.5rem] text-xs text-faint">{plan.blurb}</p>

                <div className="mt-4 flex items-baseline gap-1.5">
                  <span className="font-heading text-4xl font-extrabold text-cream">
                    {plan.credits}
                  </span>
                  <span className="text-sm text-faint">credits / month</span>
                </div>

                <ul className="mt-6 space-y-2.5">
                  {plan.perks.map((perk) => (
                    <li key={perk} className="flex items-center gap-2 text-sm text-cream">
                      <Check className="size-4 shrink-0 text-accent" />
                      {perk}
                    </li>
                  ))}
                </ul>

                <a
                  href={`${APP_URL}/signup`}
                  className={cn(
                    "mt-7",
                    plan.highlight ? "btn-primary" : "btn-secondary",
                    "w-full",
                  )}
                >
                  {plan.cta}
                </a>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* --------------------------------------------------------- PRIVACY -- */}
      <section className="mx-auto max-w-content px-4 pb-4 sm:px-6 lg:px-8">
        <Reveal>
          <div className="panel flex items-start gap-4 p-6 sm:p-8">
            <Shield className="mt-0.5 size-7 shrink-0 text-accent" />
            <div>
              <h2 className="font-heading text-xl font-bold text-cream">
                Your audio stays private
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-faint">
                Narration is processed only to build your video and is tied to your
                account — never shared or sold, and never used to train anything.
                Your finished videos are yours to download and publish.
              </p>
            </div>
          </div>
        </Reveal>
      </section>

      {/* ---------------------------------------------------------------- FAQ */}
      <section id="faq" className="mx-auto max-w-3xl px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <Reveal className="text-center">
          <span className="chip">Questions</span>
          <h2 className="mt-4 font-heading text-3xl font-bold text-cream sm:text-4xl">
            Frequently asked
          </h2>
        </Reveal>

        <div className="mt-10 space-y-3">
          {FAQS.map((faq, i) => (
            <Reveal key={faq.q} delay={(i % 4) * 60}>
              <details className="panel group p-0 [&_summary]:list-none">
                <summary className="flex cursor-pointer items-center justify-between gap-4 p-5 text-cream">
                  <span className="font-medium">{faq.q}</span>
                  <span className="grid size-7 shrink-0 place-items-center rounded-full border border-hairline text-faint transition-transform duration-300 group-open:rotate-45">
                    <span className="text-lg leading-none">+</span>
                  </span>
                </summary>
                <p className="px-5 pb-5 text-sm leading-relaxed text-faint">{faq.a}</p>
              </details>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ----------------------------------------------------------- CTA BAND */}
      <section className="mx-auto max-w-content px-4 pb-24 sm:px-6 lg:px-8">
        <Reveal>
          <div className="panel relative overflow-hidden p-10 text-center sm:p-16">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(40rem_20rem_at_50%_-20%,var(--glow),transparent)]"
            />
            <h2 className="mx-auto max-w-2xl font-heading text-3xl font-bold text-cream sm:text-4xl">
              Your next video is one narration away
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-balance text-faint">
              Start free with monthly credits — no card required. Upload or record
              your audio or video and watch Brollio build the rest.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <a href={`${APP_URL}/signup`} className="btn-primary btn-lg">
                Start free
                <ArrowRight className="size-4" />
              </a>
              <Link href="#pricing" className="btn-secondary btn-lg">
                Compare plans
              </Link>
            </div>
          </div>
        </Reveal>
      </section>

      <SiteFooter />
    </div>
  );
}
