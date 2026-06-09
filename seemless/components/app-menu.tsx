"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import {
  FolderOpen,
  Info,
  LogIn,
  LogOut,
  Menu,
  Plus,
  Sparkles,
  Tag,
  User,
  X,
  Zap,
} from "lucide-react";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";
import { useMe } from "@/lib/use-me";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  desc: string;
  icon: React.ComponentType<{ className?: string }>;
};

// Primary navigation shown to everyone. Each item explains itself so the menu
// doubles as a lightweight site map.
const NAV: NavItem[] = [
  { href: "/", label: "New video", desc: "Start from a narration", icon: Plus },
  { href: "/projects", label: "Your projects", desc: "All your videos & their status", icon: FolderOpen },
  { href: "/pricing", label: "Pricing & credits", desc: "Plans and how credits work", icon: Tag },
  { href: "/about", label: "About Brollio", desc: "What this is and how it works", icon: Info },
];

/**
 * Global navigation drawer.
 *
 * Renders a hamburger trigger and a left-side slide-in panel (Radix Dialog, so
 * focus trapping, scroll lock, Escape-to-close and ARIA are handled for us).
 * Drop `<AppMenu />` at the start of any page header. Navigation links close the
 * drawer on click, and it auto-closes on route change.
 */
export function AppMenu({ className }: { className?: string }) {
  const [open, setOpen] = React.useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const { me } = useMe();

  // Close on client-side navigation (covers programmatic pushes too).
  React.useEffect(() => {
    setOpen(false);
  }, [pathname]);

  async function signOut() {
    setOpen(false);
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className={className}
          aria-label="Open menu"
        >
          <Menu className="size-5" />
        </Button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
        <Dialog.Content
          className={cn(
            "fixed inset-y-0 left-0 z-50 flex h-full w-[300px] max-w-[85vw] flex-col border-r border-hairline bg-panel shadow-2xl outline-none",
            "data-[state=open]:animate-in data-[state=open]:slide-in-from-left data-[state=open]:duration-300",
            "data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=closed]:duration-200",
          )}
        >
          <div className="flex items-center justify-between border-b border-hairline px-4 py-3.5">
            <Dialog.Title asChild>
              <Link href="/" className="shrink-0">
                <Brand size="sm" />
              </Link>
            </Dialog.Title>
            <Dialog.Close asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label="Close menu">
                <X className="size-5" />
              </Button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">
            Main navigation for Brollio.
          </Dialog.Description>

          <nav className="flex-1 overflow-y-auto p-3">
            <ul className="space-y-1">
              {NAV.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Dialog.Close asChild>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors",
                          active
                            ? "bg-accent/10 text-cream"
                            : "text-faint hover:bg-panel-raised hover:text-cream",
                        )}
                      >
                        <item.icon
                          className={cn(
                            "mt-0.5 size-5 shrink-0",
                            active ? "text-accent" : "text-faint group-hover:text-accent",
                          )}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm font-medium">{item.label}</span>
                          <span className="block text-xs text-faint">{item.desc}</span>
                        </span>
                      </Link>
                    </Dialog.Close>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="border-t border-hairline p-3">
            {me ? (
              <div className="space-y-2">
                <Dialog.Close asChild>
                  <Link
                    href="/account"
                    className="flex items-center justify-between rounded-lg bg-panel-raised px-3 py-2.5 transition-colors hover:bg-panel-hover"
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <User className="size-5 shrink-0 text-faint" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-cream">
                          {me.email ?? "Account"}
                        </span>
                        <span className="block text-xs text-faint">
                          {me.tier_info.label} plan
                        </span>
                      </span>
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-xs font-medium text-cream">
                      <Zap className="size-3 text-accent" />
                      {me.credits}
                    </span>
                  </Link>
                </Dialog.Close>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  onClick={signOut}
                >
                  <LogOut className="size-4" />
                  Sign out
                </Button>
              </div>
            ) : (
              <Dialog.Close asChild>
                <Button variant="secondary" className="w-full" asChild>
                  <Link href="/login">
                    <LogIn className="size-4" />
                    Sign in
                  </Link>
                </Button>
              </Dialog.Close>
            )}
            <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-[11px] text-faint/70">
              <Sparkles className="size-3" />
              Narration to faceless video
            </p>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
