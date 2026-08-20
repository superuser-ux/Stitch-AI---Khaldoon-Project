"use client";

import { createContext, useContext, useEffect, useState } from "react";

type SessionState = {
  loading: boolean;
  iam: boolean;
  authenticated: boolean;
  unbound: boolean;
  principalId: string | null;
  display: string | null;
};

const SessionContext = createContext<SessionState>({
  loading: true,
  iam: false,
  authenticated: false,
  unbound: false,
  principalId: null,
  display: null,
});

export function IamProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<SessionState>({
    loading: true,
    iam: false,
    authenticated: false,
    unbound: false,
    principalId: null,
    display: null,
  });
  useEffect(() => {
    let active = true;
    fetch("/api/auth/session", { cache: "no-store" })
      .then((response) => response.json())
      .then((session) => {
        if (!active) return;
        setState({
          loading: false,
          iam: Boolean(session.iam),
          authenticated: Boolean(session.authenticated),
          unbound: Boolean(session.unbound),
          principalId: session.principal_id ?? null,
          display: session.display ?? null,
        });
      })
      .catch(() => active && setState((current) => ({ ...current, loading: false, iam: true })));
    return () => { active = false; };
  }, []);
  return <SessionContext.Provider value={state}>{children}</SessionContext.Provider>;
}

async function signOut() {
  const response = await fetch("/api/auth/logout", { method: "POST" });
  const result = await response.json().catch(() => ({ redirect: "/" }));
  window.location.assign(result.redirect || "/");
}

export function IamAccount() {
  const session = useContext(SessionContext);
  if (!session.iam || !session.authenticated) return null;
  return (
    <div className="flex items-center gap-2" data-testid="iam-account">
      <span className="max-w-32 truncate text-xs text-(--color-muted)" title={session.principalId || undefined}>
        {session.display || session.principalId || "Unassigned"}
      </span>
      <button
        type="button"
        data-testid="iam-signout"
        onClick={() => { void signOut(); }}
        className="rounded-md border border-(--color-border) px-2 py-1 text-xs hover:bg-(--color-bg)"
      >
        Sign out
      </button>
    </div>
  );
}

export function IamBoundary({ children }: { children: React.ReactNode }) {
  const session = useContext(SessionContext);
  if (session.loading) {
    return <div className="mx-auto max-w-xl py-16 text-center text-sm text-(--color-muted)">Checking sign-in…</div>;
  }
  if (!session.iam) return children;
  if (!session.authenticated) {
    const error = typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("auth_error");
    return (
      <div className="mx-auto max-w-xl rounded-xl border border-(--color-border) bg-(--color-panel) p-6" data-testid="iam-entry">
        <p className="text-xs font-medium uppercase tracking-wide text-(--color-muted)">Tanaghom identity</p>
        <h1 className="mt-2 text-xl font-semibold">Sign in to the workbench</h1>
        <p className="mt-2 text-sm text-(--color-muted)">
          Your sign-in provider proves who you are. Tanaghom separately decides your roles,
          capabilities, assignments, and approvals.
        </p>
        {error && <p className="mt-3 rounded-md border border-(--color-danger) bg-(--color-danger-soft) p-2 text-sm">{error}</p>}
        <a
          href="/api/auth/login"
          data-testid="iam-login"
          className="mt-5 inline-flex rounded-md bg-(--color-accent) px-4 py-2 text-sm font-semibold text-white"
        >
          Continue to sign in
        </a>
      </div>
    );
  }
  if (session.unbound) {
    return (
      <div className="mx-auto max-w-xl rounded-xl border border-(--color-border) bg-(--color-panel) p-6" data-testid="iam-unbound">
        <h1 className="text-xl font-semibold">Access is not configured</h1>
        <p className="mt-2 text-sm text-(--color-muted)">
          This sign-in account is valid, but it is not connected to an active Tanaghom user.
          Ask a Tanaghom administrator to connect it, then sign in again.
        </p>
        <button type="button" onClick={() => { void signOut(); }} className="mt-5 rounded-md border border-(--color-border) px-4 py-2 text-sm">
          Sign out
        </button>
      </div>
    );
  }
  return children;
}
