"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Toggles the light/dark theme by flipping the `dark` class on <html> and
 * persisting the choice. Icons swap purely via the `dark:` variant, so there's
 * no React state to hydrate (and no flash).
 */
export function ThemeToggle({ className }: { className?: string }) {
  const toggle = () => {
    const root = document.documentElement;
    const isDark = root.classList.toggle("dark");
    root.classList.toggle("light", !isDark);
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch {
      // ignore storage failures (private mode, etc.)
    }
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={toggle}
      className={className}
      aria-label="Toggle light and dark theme"
      title="Toggle theme"
    >
      <Sun className="hidden size-4 dark:block" />
      <Moon className="block size-4 dark:hidden" />
    </Button>
  );
}
