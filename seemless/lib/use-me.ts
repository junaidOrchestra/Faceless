"use client";

import * as React from "react";

export type TierInfo = {
  name: string;
  label: string;
  monthly_credits: number;
  max_video_seconds: number;
  max_resolution_height: number;
  watermark: boolean;
  unlimited_credits?: boolean;
  features: string[];
};

export type Me = {
  id: string;
  email: string | null;
  name: string | null;
  tier: string;
  credits: number;
  tier_info: TierInfo;
};

type State = { me: Me | null; loading: boolean; error: string | null };

// --- Shared, cached store ---------------------------------------------------
//
// `/api/me` is hit by several header/menu components at once (credit badge,
// header actions, app menu, feedback widget). Without sharing, each mount fired
// its own request and showed nothing until it resolved — so the credits/projects
// controls visibly popped in on a cold backend. A single module-level store:
//   * dedupes concurrent fetches into ONE request, and
//   * keeps the result cached across route changes / remounts, so after the
//     first load the controls render instantly.

const STORAGE_KEY = "brollio:me";

let snapshot: State = { me: null, loading: true, error: null };
let inflight: Promise<void> | null = null;
let hydratedFromStorage = false;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function setSnapshot(next: State): void {
  snapshot = next;
  emit();
}

function persist(me: Me | null): void {
  if (typeof window === "undefined") return;
  try {
    if (me) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(me));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // sessionStorage can throw (private mode / quota) — caching is best-effort.
  }
}

// Seed the store from the last-known value (this tab/session) so a reload shows
// real credits/projects immediately instead of a skeleton; a background
// revalidate then corrects it. Client-only and run once.
function hydrateFromStorage(): void {
  if (hydratedFromStorage) return;
  hydratedFromStorage = true;
  if (typeof window === "undefined" || !snapshot.loading) return;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) setSnapshot({ me: JSON.parse(raw) as Me, loading: false, error: null });
  } catch {
    // Ignore malformed cache.
  }
}

function loadMe(force = false): Promise<void> {
  if (inflight) return inflight;
  // Already have a resolved snapshot and not forcing a refresh: skip the fetch.
  if (!force && !snapshot.loading) return Promise.resolve();

  inflight = (async () => {
    try {
      const res = await fetch("/api/me", { cache: "no-store" });
      if (!res.ok) {
        persist(null);
        setSnapshot({ me: null, loading: false, error: `HTTP ${res.status}` });
        return;
      }
      const me = (await res.json()) as Me;
      persist(me);
      setSnapshot({ me, loading: false, error: null });
    } catch (e) {
      setSnapshot({
        me: null,
        loading: false,
        error: e instanceof Error ? e.message : "failed",
      });
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Client hook that loads the authenticated user's account (tier + balance) from
 * the Next proxy (`/api/me`). Backed by a shared cache so it fetches once and
 * renders instantly on subsequent mounts/navigations.
 */
export function useMe(): State & { refresh: () => void } {
  const state = React.useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => snapshot,
  );

  React.useEffect(() => {
    // Show the last-known value instantly (from this session), then revalidate
    // in the background (deduped). First-ever load falls back to the skeleton
    // until the fetch resolves.
    hydrateFromStorage();
    void loadMe(true);
  }, []);

  return { ...state, refresh: () => void loadMe(true) };
}
