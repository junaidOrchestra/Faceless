"use client";

import * as React from "react";
import Link from "next/link";
import { Clapperboard, Loader2 } from "lucide-react";
import { AppMenu } from "@/components/app-menu";
import { Brand } from "@/components/brand";
import { AudioPlayer } from "@/components/audio-player";
import { CreditBadge } from "@/components/account/credit-badge";
import { Stepper } from "@/components/stepper";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useMe } from "@/lib/use-me";

function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = React.useState(false);

  React.useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  return isDesktop;
}

export function TopBar({
  fileName,
  duration,
  audioUrl,
  chosen,
  total,
  stepKey = "pick",
  onMakeVideo,
  busy = false,
  hideMakeVideo = false,
}: {
  fileName: string;
  duration: number;
  audioUrl?: string;
  chosen: number;
  total: number;
  stepKey?: string;
  onMakeVideo: () => void;
  busy?: boolean;
  hideMakeVideo?: boolean;
}) {
  const ready = total > 0 && chosen >= total;
  const isDesktop = useIsDesktop();
  const { me } = useMe();
  // Gate rendering when the balance is exhausted; the cost is charged per render
  // server-side, but a zero balance can never afford one.
  const noCredits = me != null && me.credits <= 0;
  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-canvas/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:px-6">
        <AppMenu />
        <Link href="/" className="shrink-0">
          <Brand size="sm" />
        </Link>

        <div className="hidden h-8 w-px bg-hairline lg:block" />

        {isDesktop && (
          <div className="min-w-0 flex-1">
            <AudioPlayer fileName={fileName} duration={duration} audioUrl={audioUrl} />
          </div>
        )}

        <div className="ml-auto flex items-center gap-3">
          <span className="hidden font-mono text-xs text-faint sm:inline">
            <span className={ready ? "text-accent" : "text-cream"}>{chosen}</span> / {total}{" "}
            chosen
          </span>
          <CreditBadge className="hidden sm:inline-flex" />
          <ThemeToggle />
          {!hideMakeVideo &&
            (noCredits ? (
              <Button variant="primary" asChild>
                <Link href="/account">
                  <Clapperboard className="size-4" />
                  Upgrade to render
                </Link>
              </Button>
            ) : (
              <Button variant="primary" disabled={!ready || busy} onClick={onMakeVideo}>
                {busy ? (
                  <>
                    <Loader2 className="size-4 animate-spin" />
                    Rendering…
                  </>
                ) : (
                  <>
                    <Clapperboard className="size-4" />
                    Make video
                  </>
                )}
              </Button>
            ))}
        </div>
      </div>

      {/* Mobile audio row + stepper */}
      <div className="border-t border-hairline/60 px-4 py-2 sm:px-6">
        {!isDesktop && <div className="mb-2">
          <AudioPlayer fileName={fileName} duration={duration} audioUrl={audioUrl} />
        </div>}
        <Stepper current={stepKey} />
      </div>
    </header>
  );
}
