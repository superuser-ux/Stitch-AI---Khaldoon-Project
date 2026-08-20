"use client";
import { useEffect, useState } from "react";

// #180 — the SERVER decides which surface this is. The `client_trial` cookie (set by middleware on
// genuine trial servers) remains an ADVISORY presentation hint only: it pre-paints trial cosmetics
// so the locked surface never flashes operator chrome, but the server-declared runtime identity
// from /api/runtime is authoritative and corrects any stale browser state — a leftover trial
// cookie can no longer hide operator controls on an operator/dev surface (the Opera incident).
// Real access control was never here: middleware blocks routes server-side regardless.

export type RuntimeInfo = {
  surface: "operator" | "client-trial"; build: string;
  identity?: "oidc" | "demo";   // #190 — how this server establishes identity
};

let runtimePromise: Promise<RuntimeInfo | null> | null = null;
export function fetchRuntime(): Promise<RuntimeInfo | null> {
  if (!runtimePromise) {
    runtimePromise = fetch("/api/runtime", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return runtimePromise;
}

export function useClientTrialMode(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (typeof document !== "undefined") {
      // advisory pre-paint only — overridden by the server answer below
      setOn(document.cookie.split(";").some((c) => c.trim() === "client_trial=1"));
    }
    let cancelled = false;
    fetchRuntime().then((rt) => {
      // fail-safe: if the runtime read fails, keep the advisory cookie value (a genuine trial
      // surface keeps its cookie fresh via middleware; an operator surface actively deletes it)
      if (!cancelled && rt?.surface) setOn(rt.surface === "client-trial");
    });
    return () => { cancelled = true; };
  }, []);
  return on;
}

// #180 — the self-identification badge's server-declared half (surface + build).
export function useRuntimeInfo(): RuntimeInfo | null {
  const [info, setInfo] = useState<RuntimeInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchRuntime().then((rt) => { if (!cancelled) setInfo(rt); });
    return () => { cancelled = true; };
  }, []);
  return info;
}

// #180 — user-facing recovery: clear ONLY Tanaghom-owned browser state (tanaghom-* local/session
// keys, the trial cosmetic cookie, and the Tanaghom reviewer cookie via its own API) and reload.
// Never touches other sites' or the browser's general data.
export async function resetLocalViewState() {
  try {
    for (const store of [window.localStorage, window.sessionStorage]) {
      for (const key of Object.keys(store)) {
        if (key.startsWith("tanaghom")) store.removeItem(key);
      }
    }
  } catch { /* storage blocked — cookie + reload still help */ }
  document.cookie = "client_trial=; path=/; max-age=0";
  try { await fetch("/api/reviewer", { method: "DELETE" }); } catch { /* best-effort */ }
  window.location.reload();
}
