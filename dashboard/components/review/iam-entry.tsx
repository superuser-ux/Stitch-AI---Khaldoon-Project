"use client";

import { useEffect, useState } from "react";
import { LogIn, ShieldQuestion } from "lucide-react";
import { useReview } from "@/lib/review-context";

// #190 (#172 S1) — the IAM-mode identity surfaces. Two truthful states, no fallbacks:
//   unauthenticated          → sign in via the BFF's OIDC flow;
//   authenticated + unbound  → "no operating identity assigned": the IdP proved WHO you are, but
//                              no operator has bound that identity to a Tanaghom principal, so
//                              there is nothing you can act as. Deliberately NOT a persona picker —
//                              demo identity selection never leaks into IAM mode.
// Cosmetic layer only: /gw refuses to sign for these states server-side regardless.
export function IamEntry() {
  const r = useReview();
  const [authError, setAuthError] = useState<string | null>(null);
  useEffect(() => {
    const err = new URL(window.location.href).searchParams.get("auth_error");
    if (err) setAuthError(err);
  }, []);
  if (!r.iam?.mode || (r.iam.authenticated && !r.iam.unbound)) return null;

  return (
    <div
      data-testid="iam-entry"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-background/95 p-6 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-2xl border border-border/80 bg-card p-6 shadow-xl">
        {!r.iam.authenticated ? (
          <>
            <h1 className="text-lg font-semibold">Sign in to Tanaghom</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Use your organization account to continue.
            </p>
            {authError && (
              <p data-testid="iam-auth-error" className="mt-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs">
                Sign-in failed: {authError}
              </p>
            )}
            <a
              data-testid="iam-login"
              href="/api/auth/login"
              className="mt-5 inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              <LogIn className="size-4" /> Sign in
            </a>
          </>
        ) : (
          <>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-warning">
              <ShieldQuestion className="size-3.5" /> Account not set up
            </span>
            <h1 className="mt-4 text-lg font-semibold">You&apos;re signed in, but your account isn&apos;t set up yet</h1>
            <p className="mt-2 text-sm text-muted-foreground" data-testid="iam-unbound">
              You signed in{r.iam.email ? <> as <span className="font-medium text-foreground">{r.iam.email}</span></> : null},
              but this account doesn&apos;t have access to Tanaghom yet. Please ask your
              administrator to set up your access, then sign in again.
            </p>
            <button
              type="button"
              data-testid="iam-signout"
              className="mt-5 rounded-xl border border-border px-4 py-2.5 text-sm font-medium hover:bg-secondary"
              onClick={async () => {
                const response = await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
                const result = await response?.json().catch(() => null);
                window.location.href = result?.redirect || "/";
              }}
            >
              Sign out
            </button>
          </>
        )}
      </div>
    </div>
  );
}
