// Server-only orchestrator connection settings. The user's Supabase access
// token is attached server-side as the Bearer credential, so the backend URL
// and the token-minting flow never reach the browser. The browser only ever
// talks to the Next.js proxy routes in app/api/*.

import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const ORCHESTRATOR_URL =
  process.env.ORCHESTRATOR_URL ?? "http://localhost:8000";

/**
 * Resolve the current user's Supabase access token from the session cookies.
 * Returns null when there is no session (the proxy then surfaces a 401).
 */
export async function getAccessToken(): Promise<string | null> {
  try {
    const supabase = await createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ?? null;
  } catch {
    return null;
  }
}

export async function orchHeaders(extra?: HeadersInit): Promise<HeadersInit> {
  const token = await getAccessToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

// Per-route upstream timeouts (ms). A hung orchestrator must never hold a Next
// server request open forever, so every proxy fetch is bounded. Polling routes
// are short; the multipart upload is generous; the streaming proxies bound only
// time-to-first-byte (see orchFetch) so a large file isn't cut off mid-stream.
export const ORCH_TIMEOUT = {
  status: 12_000,
  beats: 12_000,
  mutate: 20_000,
  upload: 180_000,
  streamTtfb: 30_000,
} as const;

/**
 * fetch() to the orchestrator with an abort-based timeout.
 *
 * The timer is cleared as soon as the response *headers* arrive (when the fetch
 * promise resolves), so it bounds time-to-first-byte only. That keeps small
 * JSON routes safe while letting the streaming proxies (download/audio) stream
 * an arbitrarily large body without being aborted partway through.
 */
export async function orchFetch(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<Response> {
  const { timeoutMs = ORCH_TIMEOUT.mutate, headers, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${ORCHESTRATOR_URL}${path}`, {
      ...rest,
      headers: await orchHeaders(headers),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export function isAbortError(e: unknown): boolean {
  return (
    e instanceof Error && (e.name === "AbortError" || e.name === "TimeoutError")
  );
}

/**
 * Map an orchFetch failure to a JSON proxy response: 504 when we timed out
 * waiting for the upstream, 502 for any other connection failure. ``fallback``
 * is merged into the body so callers that expect a shape (e.g. { beats: [] })
 * still parse cleanly.
 */
export function upstreamErrorResponse(
  e: unknown,
  fallback: Record<string, unknown> = {},
): NextResponse {
  const timedOut = isAbortError(e);
  return NextResponse.json(
    {
      ...fallback,
      error: timedOut ? "Upstream timed out" : "Upstream unreachable",
    },
    { status: timedOut ? 504 : 502 },
  );
}
