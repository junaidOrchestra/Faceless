import { NextResponse } from "next/server";

export const runtime = "nodejs";

// ⚠️ TEMPORARY — overlay-harvesting helper for /dev/transitions only.
// Proxies Pixabay search so the dev page can browse royalty-free clips/photos
// and emit `effect_overlays` INSERTs. Delete this route (and app/dev/transitions)
// once the table is seeded. The key is a throwaway provided for this task; move
// it to an env var if you keep this around.
const PIXABAY_KEY = process.env.PIXABAY_API_KEY ?? "56178382-da7bd986ba8e19f855a70d7a3";

type NormalizedHit = {
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

type PixabayVideoFile = { url?: string; width?: number; height?: number; thumbnail?: string };

function normalizeVideos(hits: unknown[]): NormalizedHit[] {
  const out: NormalizedHit[] = [];
  for (const raw of hits) {
    const h = raw as {
      id?: number;
      pageURL?: string;
      duration?: number;
      tags?: string;
      user?: string;
      videos?: Record<string, PixabayVideoFile>;
    };
    const v = h.videos ?? {};
    // Overlays are short, soft textures cover-scaled by the backend, so prefer
    // the SMALLEST decent resolution — far less to download/stream for a ~0.3s
    // clip than the medium/large variants.
    const file = v.small?.url ? v.small : v.tiny?.url ? v.tiny : v.medium?.url ? v.medium : v.large;
    if (!file?.url) continue;
    out.push({
      externalId: String(h.id ?? ""),
      mediaUrl: file.url,
      previewUrl: file.thumbnail || v.large?.thumbnail || v.medium?.thumbnail || null,
      width: file.width ?? null,
      height: file.height ?? null,
      durationS: typeof h.duration === "number" ? h.duration : null,
      attribution: h.user ? `${h.user} (Pixabay)` : "Pixabay",
      pageUrl: h.pageURL ?? null,
      tags: h.tags ?? null,
    });
  }
  return out;
}

function normalizeImages(hits: unknown[]): NormalizedHit[] {
  const out: NormalizedHit[] = [];
  for (const raw of hits) {
    const h = raw as {
      id?: number;
      pageURL?: string;
      tags?: string;
      user?: string;
      previewURL?: string;
      webformatURL?: string;
      largeImageURL?: string;
      imageWidth?: number;
      imageHeight?: number;
    };
    const mediaUrl = h.largeImageURL || h.webformatURL;
    if (!mediaUrl) continue;
    out.push({
      externalId: String(h.id ?? ""),
      mediaUrl,
      previewUrl: h.webformatURL || h.previewURL || null,
      width: h.imageWidth ?? null,
      height: h.imageHeight ?? null,
      durationS: null,
      attribution: h.user ? `${h.user} (Pixabay)` : "Pixabay",
      pageUrl: h.pageURL ?? null,
      tags: h.tags ?? null,
    });
  }
  return out;
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = (searchParams.get("q") ?? "").trim();
  const type = searchParams.get("type") === "image" ? "image" : "video";
  const perPage = Math.min(50, Math.max(3, Number(searchParams.get("per_page") ?? 24) || 24));
  if (!q) return NextResponse.json({ results: [] });

  const base = type === "video" ? "https://pixabay.com/api/videos/" : "https://pixabay.com/api/";
  const url = new URL(base);
  url.searchParams.set("key", PIXABAY_KEY);
  url.searchParams.set("q", q.slice(0, 100));
  url.searchParams.set("per_page", String(perPage));
  url.searchParams.set("safesearch", "true");
  if (type === "image") url.searchParams.set("image_type", "all");

  try {
    const res = await fetch(url.toString(), { headers: { "User-Agent": "FacelessFlow/dev" } });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return NextResponse.json(
        { error: `Pixabay ${res.status}`, detail: text.slice(0, 300) },
        { status: 502 },
      );
    }
    const data = (await res.json()) as { hits?: unknown[]; total?: number };
    const hits = Array.isArray(data.hits) ? data.hits : [];
    const results = type === "video" ? normalizeVideos(hits) : normalizeImages(hits);
    return NextResponse.json({ results, total: data.total ?? results.length });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Pixabay request failed" },
      { status: 502 },
    );
  }
}
