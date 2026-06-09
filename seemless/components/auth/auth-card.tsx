"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/client";

type Mode = "login" | "signup";

/**
 * Email/password + "Continue with Google" auth card.
 *
 * On email login it redirects to the original destination; on sign-up it shows a
 * "confirm your email" notice (Supabase sends a confirmation link that returns
 * to /auth/callback). Google uses the OAuth code flow via /auth/callback.
 */
export function AuthCard({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const redirect = params.get("redirect") ?? "/projects";

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(
    params.get("error") ? "Authentication failed. Please try again." : null,
  );

  const supabase = React.useMemo(() => createClient(), []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "login") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        router.push(redirect);
        router.refresh();
      } else {
        const { error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(
              redirect,
            )}`,
          },
        });
        if (error) throw error;
        setNotice("Check your email to confirm your account, then sign in.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function onGoogle() {
    setBusy(true);
    setError(null);
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(
            redirect,
          )}`,
        },
      });
      if (error) throw error;
      // Redirects away to Google on success.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start Google sign-in.");
      setBusy(false);
    }
  }

  const isLogin = mode === "login";

  return (
    <div className="w-full max-w-sm space-y-6">
      <div className="flex flex-col items-center gap-3 text-center">
        <Brand />
        <h1 className="font-heading text-2xl font-bold text-cream">
          {isLogin ? "Welcome back" : "Create your account"}
        </h1>
        <p className="text-sm text-faint">
          {isLogin
            ? "Sign in to turn narration into faceless video."
            : "Start with free monthly credits — no card required."}
        </p>
      </div>

      <div className="panel space-y-4 p-6">
        <Button
          type="button"
          variant="secondary"
          className="w-full"
          onClick={onGoogle}
          disabled={busy}
        >
          <GoogleGlyph />
          Continue with Google
        </Button>

        <div className="flex items-center gap-3 text-xs text-faint">
          <span className="h-px flex-1 bg-hairline" />
          or
          <span className="h-px flex-1 bg-hairline" />
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          <Input
            type="email"
            required
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            type="password"
            required
            minLength={6}
            autoComplete={isLogin ? "current-password" : "new-password"}
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && <p className="text-sm text-red-400">{error}</p>}
          {notice && <p className="text-sm text-accent">{notice}</p>}

          <Button type="submit" variant="primary" className="w-full" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {isLogin ? "Sign in" : "Sign up"}
          </Button>
        </form>
      </div>

      <p className="text-center text-sm text-faint">
        {isLogin ? "New here? " : "Already have an account? "}
        <Link
          href={isLogin ? "/signup" : "/login"}
          className="font-medium text-accent hover:underline"
        >
          {isLogin ? "Create an account" : "Sign in"}
        </Link>
      </p>
    </div>
  );
}

function GoogleGlyph() {
  return (
    <svg className="size-4" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.56c2.08-1.92 3.28-4.74 3.28-8.09Z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.56-2.76c-.98.66-2.23 1.06-3.72 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38Z"
      />
    </svg>
  );
}
