"use client";

// ⚠️ TEMPORARY — overlay-harvesting tool. Search Pixabay (royalty-free), pick the
// clips/photos you want per visual category, then copy the generated SQL into
// psql to seed `effect_overlays`. Delete this page + app/api/pixabay-dev once done.

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EFFECT_VISUALS } from "@/lib/effects";
import { cn } from "@/lib/utils";

type MediaType = "video" | "image";

type Hit = {
  externalId: string;
  mediaUrl: string;
  previewUrl: string | null;
  width: number | null;
  height: number | null;
  durationS: number | null;
  attribution: string | null;
  pageUrl: string | null;
  tags: string | null;
};

type CartItem = Hit & { category: string };

const CATEGORIES = EFFECT_VISUALS.filter((v) => v.id !== "none");

function sqlStr(v: string | null): string {
  if (v == null) return "NULL";
  return `'${v.replace(/'/g, "''")}'`;
}

function sqlNum(v: number | null): string {
  return v == null || Number.isNaN(v) ? "NULL" : String(v);
}

function buildSql(cart: CartItem[]): string {
  if (cart.length === 0) return "-- Select some clips first.";
  const byCategory = new Map<string, CartItem[]>();
  for (const item of cart) {
    const arr = byCategory.get(item.category) ?? [];
    arr.push(item);
    byCategory.set(item.category, arr);
  }
  const blocks: string[] = [];
  for (const [category, items] of byCategory) {
    const rows = items.map((it, rank) =>
      [
        sqlStr(category),
        sqlStr("pixabay"),
        sqlStr(it.externalId || null),
        sqlStr(it.mediaUrl),
        sqlStr(it.previewUrl),
        sqlStr(it.attribution),
        sqlNum(it.width),
        sqlNum(it.height),
        sqlNum(it.durationS),
        String(rank),
        "TRUE",
      ].join(", "),
    );
    blocks.push(
      `INSERT INTO effect_overlays\n` +
        `  (category, source, external_id, media_url, preview_url, attribution, width, height, duration_s, rank, active)\n` +
        `VALUES\n  (${rows.join("),\n  (")})\n` +
        `ON CONFLICT (category, media_url) DO UPDATE SET\n` +
        `  source = EXCLUDED.source,\n` +
        `  external_id = EXCLUDED.external_id,\n` +
        `  preview_url = EXCLUDED.preview_url,\n` +
        `  attribution = EXCLUDED.attribution,\n` +
        `  width = EXCLUDED.width,\n` +
        `  height = EXCLUDED.height,\n` +
        `  duration_s = EXCLUDED.duration_s,\n` +
        `  rank = EXCLUDED.rank,\n` +
        `  active = TRUE;`,
    );
  }
  return blocks.join("\n\n");
}

export default function TransitionsDevPage() {
  const [query, setQuery] = React.useState("light leak overlay");
  const [mediaType, setMediaType] = React.useState<MediaType>("video");
  const [category, setCategory] = React.useState<string>(CATEGORIES[0]?.id ?? "light_leak");
  const [results, setResults] = React.useState<Hit[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [cart, setCart] = React.useState<Record<string, CartItem>>({});
  const [copied, setCopied] = React.useState(false);

  const cartItems = React.useMemo(() => Object.values(cart), [cart]);
  const sql = React.useMemo(() => buildSql(cartItems), [cartItems]);

  const search = React.useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/pixabay-dev?type=${mediaType}&q=${encodeURIComponent(q)}&per_page=40`,
      );
      const data = (await res.json()) as { results?: Hit[]; error?: string };
      if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      setResults(data.results ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, mediaType]);

  const toggle = (hit: Hit) => {
    setCart((prev) => {
      const next = { ...prev };
      if (next[hit.mediaUrl]) delete next[hit.mediaUrl];
      else next[hit.mediaUrl] = { ...hit, category };
      return next;
    });
  };

  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — user can select manually */
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold text-cream">Transition overlay harvester</h1>
        <p className="text-sm text-faint">
          Temporary tool. Pick a category, search Pixabay, click clips to add them, then copy
          the SQL into psql to seed <code className="text-cream">effect_overlays</code>.
        </p>
      </header>

      {/* Category chips */}
      <div className="flex flex-wrap gap-2">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              setCategory(c.id);
              setQuery(c.query);
            }}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              category === c.id
                ? "border-accent bg-accent/10 text-accent"
                : "border-hairline text-faint hover:text-cream",
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Search bar */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="Search Pixabay…"
          className="max-w-md"
        />
        <div className="flex overflow-hidden rounded-lg border border-hairline">
          {(["video", "image"] as MediaType[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setMediaType(t)}
              className={cn(
                "px-3 py-2 text-xs capitalize",
                mediaType === t ? "bg-accent/15 text-accent" : "text-faint hover:text-cream",
              )}
            >
              {t}
            </button>
          ))}
        </div>
        <Button variant="primary" onClick={search} disabled={loading}>
          {loading ? "Searching…" : "Search"}
        </Button>
        <span className="text-xs text-faint">
          adding to <span className="text-cream">{category}</span> · {cartItems.length} selected
        </span>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {/* Results grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {results.map((hit) => {
          const selected = !!cart[hit.mediaUrl];
          return (
            <button
              key={hit.mediaUrl}
              type="button"
              onClick={() => toggle(hit)}
              className={cn(
                "group relative overflow-hidden rounded-lg border bg-black text-left",
                selected ? "border-accent ring-2 ring-accent/40" : "border-hairline",
              )}
            >
              {mediaType === "video" ? (
                <video
                  src={`/api/media-proxy?url=${encodeURIComponent(hit.mediaUrl)}`}
                  poster={hit.previewUrl ?? undefined}
                  muted
                  loop
                  playsInline
                  onMouseEnter={(e) => void e.currentTarget.play().catch(() => {})}
                  onMouseLeave={(e) => {
                    e.currentTarget.pause();
                    e.currentTarget.currentTime = 0;
                  }}
                  className="aspect-video w-full object-cover"
                />
              ) : (
                <img
                  src={hit.previewUrl ?? hit.mediaUrl}
                  alt={hit.tags ?? "result"}
                  className="aspect-video w-full object-cover"
                />
              )}
              <div className="flex items-center justify-between px-2 py-1 text-[10px] text-faint">
                <span>
                  {hit.width ?? "?"}×{hit.height ?? "?"}
                  {hit.durationS != null && ` · ${hit.durationS}s`}
                </span>
                {selected && <span className="text-accent">✓ added</span>}
              </div>
            </button>
          );
        })}
      </div>

      {/* SQL output */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-cream">Generated SQL</h2>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setCart({})} disabled={!cartItems.length}>
              Clear
            </Button>
            <Button variant="secondary" size="sm" onClick={copySql} disabled={!cartItems.length}>
              {copied ? "Copied!" : "Copy SQL"}
            </Button>
          </div>
        </div>
        <Textarea
          readOnly
          value={sql}
          className="h-64 font-mono text-xs"
          onFocus={(e) => e.currentTarget.select()}
        />
      </div>
    </div>
  );
}
