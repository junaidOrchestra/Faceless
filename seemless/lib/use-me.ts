"use client";

import * as React from "react";

export type TierInfo = {
  name: string;
  label: string;
  monthly_credits: number;
  max_video_seconds: number;
  max_resolution_height: number;
  watermark: boolean;
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

/**
 * Client hook that loads the authenticated user's account (tier + balance) from
 * the Next proxy (`/api/me`), which attaches the Supabase token server-side.
 */
export function useMe(): State & { refresh: () => void } {
  const [state, setState] = React.useState<State>({
    me: null,
    loading: true,
    error: null,
  });

  const load = React.useCallback(async () => {
    try {
      const res = await fetch("/api/me", { cache: "no-store" });
      if (!res.ok) {
        setState({ me: null, loading: false, error: `HTTP ${res.status}` });
        return;
      }
      const me = (await res.json()) as Me;
      setState({ me, loading: false, error: null });
    } catch (e) {
      setState({
        me: null,
        loading: false,
        error: e instanceof Error ? e.message : "failed",
      });
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  return { ...state, refresh: load };
}
