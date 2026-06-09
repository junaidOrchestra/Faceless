import * as React from "react";
import { AuthCard } from "@/components/auth/auth-card";

export const metadata = { title: "Sign up — Brollio" };

export default function SignupPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <React.Suspense fallback={null}>
        <AuthCard mode="signup" />
      </React.Suspense>
    </main>
  );
}
