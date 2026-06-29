"use client";

import { signIn } from "next-auth/react";

import { Button } from "@/components/ui/button";

// Shown on the Aegra-backed /ask page when AUTH_REQUIRED is on and the operator isn't signed in
// (custom-auth mode). Centralizes the sign-in prompt.
export function SignInGate({ loading = false }: { loading?: boolean }) {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center bg-body-bg">
      <div className="flex flex-col items-center gap-4 rounded-2xl border bg-background px-10 py-12 text-center shadow-sm">
        <div className="flex size-12 items-center justify-center rounded-xl bg-ink font-mono text-xl font-semibold text-ink-foreground">
          N
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Sign in to use Nora</h2>
          <p className="mx-auto max-w-xs text-sm text-muted-foreground">
            Your conversations are private to your Google account.
          </p>
        </div>
        <Button onClick={() => signIn("google")} disabled={loading} className="rounded-full">
          {loading ? "Checking…" : "Sign in with Google"}
        </Button>
      </div>
    </div>
  );
}
