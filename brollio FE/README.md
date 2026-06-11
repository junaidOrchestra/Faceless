# Brollio — Marketing Site

The public-facing website for **Brollio**, the studio that turns a narration
voiceover into a captioned, faceless video — beat by beat.

This is a standalone [Next.js](https://nextjs.org) (App Router) marketing site.
It shares Brollio's design tokens (colors, fonts, logo) with the product app so
the two stay visually consistent, but it has **no backend** — every call to
action links into the app.

## Stack

- Next.js 16 (App Router) + React 19
- Tailwind CSS 3 with the shared Brollio token system (light + dark themes)
- `lucide-react` icons
- No external images — the hero mock is built with markup/CSS

## Getting started

```bash
npm install
npm run dev
```

Open http://localhost:3001 (or whatever port Next picks if 3000 is taken by the
app).

## Configuration

Set where the "Start free" / "Sign in" buttons point. Copy `.env.example` to
`.env.local` and adjust:

```bash
NEXT_PUBLIC_APP_URL=http://localhost:3000   # the Brollio app
```

In production, set this to the deployed app URL (e.g. `https://app.brollio.app`).

## Scripts

| Command         | Description                  |
| --------------- | ---------------------------- |
| `npm run dev`   | Start the dev server         |
| `npm run build` | Production build             |
| `npm start`     | Serve the production build   |
| `npm run lint`  | Lint with `eslint-config-next` |

## Structure

```
app/
  layout.tsx     fonts, metadata, pre-paint theme script
  page.tsx       the landing page (hero, steps, features, pricing, FAQ, CTA)
  globals.css    shared design tokens + component/utility classes
  icon.svg       favicon (Brollio film-strip mark)
components/
  site-nav.tsx     sticky nav + mobile sheet + theme toggle
  site-footer.tsx  footer
  hero-preview.tsx faux "pick clips" product mock
  brand.tsx        logo mark + wordmark
  reveal.tsx       scroll-into-view animation wrapper
  theme-toggle.tsx light/dark switch
lib/
  utils.ts       cn() helper + APP_URL
```

## Editing content

- **Copy / sections**: `app/page.tsx` (arrays for `STEPS`, `FEATURES`, `PLANS`, `FAQS`).
- **Pricing**: keep `PLANS` roughly in sync with the app's `tiers.py` — this page
  is informational; the orchestrator remains the source of truth for enforcement.
- **Theme/colors**: `app/globals.css` (CSS variables) and `tailwind.config.ts`.
