"use client";

import * as React from "react";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

/** Flips the `.dark`/`.light` class on <html> and persists the choice. */
export function ThemeToggle({ className }: { className?: string }) {
  const [dark, setDark] = React.useState(true);
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    const root = document.documentElement;
    root.classList.toggle("dark", next);
    root.classList.toggle("light", !next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      // Persisting the theme is best-effort.
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle color theme"
      className={cn(
        "grid size-9 place-items-center rounded-lg border border-hairline bg-panel text-faint transition-colors hover:text-cream hover:bg-panel-hover",
        className,
      )}
    >
      {/* Avoid an icon mismatch flash before mount. */}
      {mounted && dark ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}
