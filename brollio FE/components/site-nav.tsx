"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Menu, X } from "lucide-react";
import { Brand } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { APP_URL, cn } from "@/lib/utils";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#vibes", label: "Vibes" },
  { href: "#features", label: "Features" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
];

export function SiteNav() {
  const [open, setOpen] = React.useState(false);
  const [scrolled, setScrolled] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Lock body scroll while the mobile sheet is open.
  React.useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <header
      className={cn(
        "sticky top-0 z-50 border-b transition-colors duration-300",
        scrolled
          ? "border-hairline bg-canvas/80 backdrop-blur-xl"
          : "border-transparent bg-transparent",
      )}
    >
      <nav className="mx-auto flex h-16 max-w-content items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link href="#top" className="shrink-0" aria-label="Brollio home">
          <Brand size="sm" />
        </Link>

        <div className="mx-auto hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="rounded-lg px-3 py-2 text-sm font-medium text-faint transition-colors hover:text-cream"
            >
              {l.label}
            </a>
          ))}
        </div>

        <div className="ml-auto hidden items-center gap-2 md:flex">
          <ThemeToggle />
          <a href={`${APP_URL}/login`} className="btn-ghost">
            Sign in
          </a>
          <a href={`${APP_URL}/signup`} className="btn-primary">
            Start free
            <ArrowRight className="size-4" />
          </a>
        </div>

        {/* Mobile controls */}
        <div className="ml-auto flex items-center gap-2 md:hidden">
          <ThemeToggle />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            className="grid size-9 place-items-center rounded-lg border border-hairline bg-panel text-cream"
          >
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </nav>

      {/* Mobile sheet */}
      {open && (
        <div className="md:hidden">
          <div className="mx-4 mb-4 animate-scale-in rounded-2xl border border-hairline bg-panel p-2 shadow-xl">
            {LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="block rounded-lg px-4 py-3 text-sm font-medium text-cream hover:bg-panel-hover"
              >
                {l.label}
              </a>
            ))}
            <div className="mt-2 grid gap-2 border-t border-hairline p-2">
              <a
                href={`${APP_URL}/login`}
                className="btn-secondary w-full"
                onClick={() => setOpen(false)}
              >
                Sign in
              </a>
              <a
                href={`${APP_URL}/signup`}
                className="btn-primary w-full"
                onClick={() => setOpen(false)}
              >
                Start free
                <ArrowRight className="size-4" />
              </a>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
