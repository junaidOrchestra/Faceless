import Link from "next/link";
import { Brand } from "@/components/brand";
import { APP_URL } from "@/lib/utils";

const COLUMNS: { title: string; links: { label: string; href: string }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "How it works", href: "#how" },
      { label: "Vibes", href: "#vibes" },
      { label: "Features", href: "#features" },
      { label: "Pricing", href: "#pricing" },
      { label: "FAQ", href: "#faq" },
    ],
  },
  {
    title: "Get started",
    links: [
      { label: "Create a video", href: `${APP_URL}/signup` },
      { label: "Sign in", href: `${APP_URL}/login` },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About", href: "#how" },
      { label: "Privacy", href: "#faq" },
    ],
  },
];

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-hairline">
      <div className="mx-auto max-w-content px-4 py-14 sm:px-6 lg:px-8">
        <div className="grid gap-10 md:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div className="max-w-xs">
            <Brand />
            <p className="mt-4 text-sm leading-relaxed text-faint">
              Turn narration into a captioned, faceless video — beat by beat. No
              camera, no timeline.
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <p className="text-xs font-semibold uppercase tracking-wider text-faint">
                {col.title}
              </p>
              <ul className="mt-4 space-y-2.5">
                {col.links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-faint transition-colors hover:text-cream"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-3 border-t border-hairline pt-6 text-xs text-faint/70 sm:flex-row">
          <p>&copy; {year} Brollio. All rights reserved.</p>
          <p>Made for creators who tell stories with their voice.</p>
        </div>
      </div>
    </footer>
  );
}
