import { redirect } from "next/navigation";
import { MousePointerClick, Sparkles, Upload } from "lucide-react";
import { AppMenu } from "@/components/app-menu";
import { Brand } from "@/components/brand";
import { HeaderActions } from "@/components/account/header-actions";
import { MediaInput } from "@/components/media-input";
import { ThemeToggle } from "@/components/theme-toggle";
import { createClient } from "@/lib/supabase/server";

const STEPS = [
  { icon: Upload, label: "Add narration", desc: "Upload or record audio or video." },
  { icon: MousePointerClick, label: "Pick visuals", desc: "Review one clip per spoken beat." },
  { icon: Sparkles, label: "Render", desc: "Get a captioned faceless video." },
];

// The upload/home screen is owner-only: a logged-out visitor is sent to the
// login page (the de-facto landing page) before any of it renders. This is a
// server-side guard in addition to the middleware so the gate holds even if
// middleware is skipped. When Supabase isn't configured (local mock mode) the
// client has no session and we skip the redirect so the app still runs.
export default async function Home() {
  if (process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY) {
    const supabase = await createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) {
      redirect("/login");
    }
  }

  return (
    <main className="relative mx-auto flex min-h-screen max-w-3xl flex-col px-6 py-8">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AppMenu />
          <Brand />
        </div>
        <div className="flex items-center gap-2">
          <HeaderActions />
          <ThemeToggle />
        </div>
      </header>

      <div className="flex flex-1 flex-col items-center justify-center py-10">
        <div className="w-full animate-fade-rise space-y-8">
          <div className="space-y-4 text-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-hairline bg-panel px-3 py-1 text-xs text-faint">
              <span className="size-1.5 rounded-full bg-accent" />
              Brollio studio
            </span>
            <h1 className="font-heading text-4xl font-bold leading-[1.05] tracking-tight text-cream sm:text-5xl">
              Turn narration into a
              <br />
              <span className="text-accent">faceless video</span>, beat by beat.
            </h1>
            <p className="mx-auto max-w-md text-balance text-faint">
              Upload or record your voiceover — audio or video. We break it into spoken
              beats and suggest a visual for each one — you just review, swap, and render.
            </p>
          </div>

          <MediaInput />

          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {STEPS.map((s, i) => (
              <li
                key={s.label}
                className="panel flex flex-col gap-2 p-4"
                style={{ animationDelay: `${i * 60}ms` }}
              >
                <s.icon className="size-5 text-accent" />
                <div>
                  <p className="text-sm font-medium text-cream">{s.label}</p>
                  <p className="text-xs leading-relaxed text-faint">{s.desc}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <footer className="pt-6 text-center text-xs text-faint/70">
        Your audio stays private. Powered by the Brollio orchestrator.
      </footer>
    </main>
  );
}
