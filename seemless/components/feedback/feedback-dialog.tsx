"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Bug,
  Check,
  Heart,
  Lightbulb,
  Loader2,
  MessageSquareHeart,
  Send,
  Sparkles,
  Star,
  TrendingUp,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useFeedbackStore } from "@/lib/feedback-store";
import { useMe } from "@/lib/use-me";
import { cn } from "@/lib/utils";

type Category = "suggestion" | "improvement" | "bug" | "praise";

const CATEGORIES: {
  id: Category;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  placeholder: string;
}[] = [
  {
    id: "suggestion",
    label: "Idea",
    icon: Lightbulb,
    placeholder:
      "What would make Brollio more useful for you? Dream big — a feature, a workflow, anything.",
  },
  {
    id: "improvement",
    label: "Improve",
    icon: TrendingUp,
    placeholder:
      "What feels clunky or could be smoother? Tell us what slowed you down.",
  },
  {
    id: "bug",
    label: "Bug",
    icon: Bug,
    placeholder:
      "What went wrong? Steps to reproduce help us fix it fast.",
  },
  {
    id: "praise",
    label: "Love it",
    icon: Heart,
    placeholder: "What clicked for you? We love hearing what's working.",
  },
];

const MAX_LEN = 4000;

/**
 * Global feedback widget: a friendly floating button plus a single-screen modal
 * to capture suggestions, improvements, bugs, and praise. Designed to feel
 * lightweight and genuinely inviting so people actually want to help shape the
 * product. Opens via the floating button or programmatically (nav menu, CTAs)
 * through `useFeedbackStore`.
 */
export function FeedbackWidget() {
  const { open, setOpen } = useFeedbackStore();
  const { me } = useMe();

  // Only signed-in users can submit (the endpoint requires auth). Hide the
  // floating button otherwise; the dialog stays mounted for programmatic opens.
  if (!me) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Send feedback"
        className={cn(
          "group fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full",
          "border border-accent/40 bg-panel/90 px-3.5 py-3 text-sm font-medium text-cream backdrop-blur-md sm:py-2.5",
          "shadow-[0_8px_30px_-8px_rgba(0,0,0,0.5)] transition-all hover:-translate-y-0.5 hover:border-accent/70 hover:bg-panel-raised",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
        )}
      >
        <MessageSquareHeart className="size-5 text-accent transition-transform group-hover:scale-110" />
        <span className="hidden sm:inline">Feedback</span>
      </button>

      <FeedbackDialog open={open} onOpenChange={setOpen} defaultEmail={me.email} />
    </>
  );
}

function FeedbackDialog({
  open,
  onOpenChange,
  defaultEmail,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultEmail: string | null;
}) {
  const pathname = usePathname();
  const [category, setCategory] = React.useState<Category>("suggestion");
  const [message, setMessage] = React.useState("");
  const [rating, setRating] = React.useState(0);
  const [hoverRating, setHoverRating] = React.useState(0);
  const [email, setEmail] = React.useState(defaultEmail ?? "");
  const [status, setStatus] = React.useState<"idle" | "sending" | "done" | "error">(
    "idle",
  );
  const [error, setError] = React.useState<string | null>(null);

  // Reset to a clean slate whenever the dialog is (re)opened.
  React.useEffect(() => {
    if (open) {
      setCategory("suggestion");
      setMessage("");
      setRating(0);
      setHoverRating(0);
      setEmail(defaultEmail ?? "");
      setStatus("idle");
      setError(null);
    }
  }, [open, defaultEmail]);

  const active = CATEGORIES.find((c) => c.id === category) ?? CATEGORIES[0];
  const trimmed = message.trim();
  const canSubmit = trimmed.length >= 3 && status !== "sending";

  async function submit() {
    if (!canSubmit) return;
    setStatus("sending");
    setError(null);
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category,
          message: trimmed,
          rating: rating || undefined,
          email: email.trim() || undefined,
          page: pathname,
        }),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { detail?: string; error?: string };
        throw new Error(
          data.detail ??
            data.error ??
            (res.status === 429
              ? "You're sending feedback quickly — give it a moment."
              : "Something went wrong sending that. Please try again."),
        );
      }
      setStatus("done");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : "Please try again.");
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
        <Dialog.Content
          onOpenAutoFocus={(e) => {
            // Keep focus off the textarea so the heading reads first; the user
            // taps a category or the field intentionally.
            e.preventDefault();
          }}
          className={cn(
            "fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2",
            "flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-2xl border border-hairline bg-panel shadow-2xl outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-bottom-2 data-[state=open]:duration-200",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
          )}
        >
          {status === "done" ? (
            <SuccessView onClose={() => onOpenChange(false)} onAnother={() => setStatus("idle")} />
          ) : (
            <>
              {/* Header */}
              <div className="relative border-b border-hairline px-5 py-4">
                <div className="flex items-center gap-2.5">
                  <span className="flex size-9 items-center justify-center rounded-xl bg-accent/15 text-accent">
                    <Sparkles className="size-5" />
                  </span>
                  <div className="min-w-0">
                    <Dialog.Title className="font-heading text-base font-semibold text-cream">
                      Help shape Brollio
                    </Dialog.Title>
                    <Dialog.Description className="text-xs text-faint">
                      We read every note. Tell us what would make this the best
                      video tool for you.
                    </Dialog.Description>
                  </div>
                </div>
                <Dialog.Close asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Close"
                    className="absolute right-3 top-3"
                  >
                    <X className="size-5" />
                  </Button>
                </Dialog.Close>
              </div>

              {/* Body (scrolls if needed) */}
              <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5">
                {/* Category chips */}
                <div>
                  <p className="mb-2 text-xs font-medium text-faint">
                    What's on your mind?
                  </p>
                  <div className="grid grid-cols-4 gap-2">
                    {CATEGORIES.map((c) => {
                      const selected = c.id === category;
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => setCategory(c.id)}
                          aria-pressed={selected}
                          className={cn(
                            "flex flex-col items-center gap-1.5 rounded-xl border px-2 py-3 text-xs font-medium transition-all",
                            selected
                              ? "border-accent/60 bg-accent/10 text-cream"
                              : "border-hairline bg-panel-raised text-faint hover:border-hairline/80 hover:text-cream",
                          )}
                        >
                          <c.icon
                            className={cn(
                              "size-5",
                              selected ? "text-accent" : "text-faint",
                            )}
                          />
                          {c.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Message */}
                <div>
                  <label
                    htmlFor="feedback-message"
                    className="mb-2 block text-xs font-medium text-faint"
                  >
                    Your message
                  </label>
                  <textarea
                    id="feedback-message"
                    value={message}
                    onChange={(e) => setMessage(e.target.value.slice(0, MAX_LEN))}
                    placeholder={active.placeholder}
                    rows={4}
                    className={cn(
                      "w-full resize-none rounded-xl border border-hairline bg-canvas px-3.5 py-3 text-sm text-cream placeholder:text-faint/60",
                      "focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20",
                    )}
                  />
                  <div className="mt-1 flex justify-end">
                    <span className="text-[11px] text-faint/70">
                      {trimmed.length}/{MAX_LEN}
                    </span>
                  </div>
                </div>

                {/* Optional rating */}
                <div className="flex items-center justify-between rounded-xl border border-hairline bg-panel-raised px-3.5 py-3">
                  <span className="text-xs font-medium text-faint">
                    How's your experience?
                  </span>
                  <div className="flex items-center gap-1" onMouseLeave={() => setHoverRating(0)}>
                    {[1, 2, 3, 4, 5].map((n) => {
                      const filled = (hoverRating || rating) >= n;
                      return (
                        <button
                          key={n}
                          type="button"
                          aria-label={`${n} star${n > 1 ? "s" : ""}`}
                          onMouseEnter={() => setHoverRating(n)}
                          onClick={() => setRating(rating === n ? 0 : n)}
                          className="p-0.5 transition-transform hover:scale-110"
                        >
                          <Star
                            className={cn(
                              "size-5 transition-colors",
                              filled
                                ? "fill-accent text-accent"
                                : "text-faint/50",
                            )}
                          />
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Optional reply-to */}
                <div>
                  <label
                    htmlFor="feedback-email"
                    className="mb-2 block text-xs font-medium text-faint"
                  >
                    Email{" "}
                    <span className="font-normal text-faint/60">
                      (optional — so we can follow up)
                    </span>
                  </label>
                  <input
                    id="feedback-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className={cn(
                      "w-full rounded-xl border border-hairline bg-canvas px-3.5 py-2.5 text-sm text-cream placeholder:text-faint/60",
                      "focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/20",
                    )}
                  />
                </div>

                {error && (
                  <p className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {error}
                  </p>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between gap-3 border-t border-hairline px-5 py-4">
                <p className="hidden items-center gap-1.5 text-[11px] text-faint/70 sm:flex">
                  <Heart className="size-3 text-accent" />
                  Built with your feedback
                </p>
                <Button
                  type="button"
                  variant="primary"
                  onClick={submit}
                  disabled={!canSubmit}
                  className="ml-auto"
                >
                  {status === "sending" ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      Sending…
                    </>
                  ) : (
                    <>
                      <Send className="size-4" />
                      Send feedback
                    </>
                  )}
                </Button>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SuccessView({
  onClose,
  onAnother,
}: {
  onClose: () => void;
  onAnother: () => void;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <span className="flex size-14 items-center justify-center rounded-full bg-accent/15 text-accent">
        <Check className="size-7" />
      </span>
      <Dialog.Title className="mt-4 font-heading text-lg font-semibold text-cream">
        Thank you — that's genuinely helpful
      </Dialog.Title>
      <Dialog.Description className="mt-1.5 max-w-xs text-sm text-faint">
        Your note is in our inbox and helps decide what we build next. We're
        building Brollio with people like you.
      </Dialog.Description>
      <div className="mt-6 flex items-center gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={onAnother}>
          Send another
        </Button>
        <Button type="button" variant="primary" size="sm" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  );
}
