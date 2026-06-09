import * as React from "react";
import { AuthCard } from "@/components/auth/auth-card";

export const metadata = { title: "Sign in — Brollio" };

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <React.Suspense fallback={null}>
        <AuthCard mode="login" />
      </React.Suspense>
    </main>
  );
}
