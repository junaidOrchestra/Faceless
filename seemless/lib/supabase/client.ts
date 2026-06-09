import { createBrowserClient } from "@supabase/ssr";

/**
 * Browser-side Supabase client (anon key only).
 *
 * Uses the @supabase/ssr cookie pattern so the session set by the server stays
 * in sync. Never expose the service-role key here — this runs in the browser.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
