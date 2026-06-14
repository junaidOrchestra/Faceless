import { NextResponse } from "next/server";

export const runtime = "nodejs";

// GET /api/media-proxy?url=<encoded absolute url>
//
// Streams a remote media file (stock overlay clip, a beat's poster/footage)
// through THIS origin so the browser can draw it onto a <canvas> without
// tainting it (cross-origin pixels otherwise block captureStream/toBlob). Used
// only by the in-editor effect recorder. Authenticated editor tool, but we still
// guard against SSRF: https/http only, and no localhost / private-network hosts.

function isBlockedHost(hostname: string): boolean {
  const h = hostname.toLowerCase();
  if (h === "localhost" || h.endsWith(".local") || h.endsWith(".internal")) return true;
  // Literal IPv4 in a private / loopback / link-local range.
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (m) {
    const [a, b] = [Number(m[1]), Number(m[2])];
    if (a === 127 || a === 10 || a === 0) return true;
    if (a === 169 && b === 254) return true; // link-local
    if (a === 192 && b === 168) return true;
    if (a === 172 && b >= 16 && b <= 31) return true;
  }
  // IPv6 loopback / unique-local / link-local.
  if (h === "::1" || h.startsWith("fc") || h.startsWith("fd") || h.startsWith("fe80")) return true;
  return false;
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const target = searchParams.get("url");
  if (!target) {
    return NextResponse.json({ error: "Missing url" }, { status: 400 });
  }

  let parsed: URL;
  try {
    parsed = new URL(target);
  } catch {
    return NextResponse.json({ error: "Invalid url" }, { status: 400 });
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return NextResponse.json({ error: "Unsupported protocol" }, { status: 400 });
  }
  if (isBlockedHost(parsed.hostname)) {
    return NextResponse.json({ error: "Host not allowed" }, { status: 403 });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const upstream = await fetch(parsed.toString(), {
      headers: {
        // Some CDNs (Pexels) require a UA and honor Range for video seeking.
        "User-Agent": "FacelessFlow/1.0 (+editor-media-proxy)",
        ...(req.headers.get("range") ? { Range: req.headers.get("range") as string } : {}),
      },
      signal: controller.signal,
      redirect: "follow",
    });
    if (!upstream.ok && upstream.status !== 206) {
      return NextResponse.json(
        { error: `Upstream ${upstream.status}` },
        { status: 502 },
      );
    }
    const contentType = upstream.headers.get("content-type") ?? "application/octet-stream";
    // Only proxy real media — never HTML error pages, which would taint nothing
    // but also can't be drawn.
    if (!/^(image|video|audio)\//i.test(contentType)) {
      return NextResponse.json({ error: "Not a media resource" }, { status: 415 });
    }
    const headers = new Headers();
    headers.set("Content-Type", contentType);
    headers.set("Cache-Control", "private, max-age=600");
    const len = upstream.headers.get("content-length");
    if (len) headers.set("Content-Length", len);
    const range = upstream.headers.get("content-range");
    if (range) headers.set("Content-Range", range);
    const acceptRanges = upstream.headers.get("accept-ranges");
    if (acceptRanges) headers.set("Accept-Ranges", acceptRanges);
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch {
    return NextResponse.json({ error: "Upstream unreachable" }, { status: 502 });
  } finally {
    clearTimeout(timer);
  }
}
