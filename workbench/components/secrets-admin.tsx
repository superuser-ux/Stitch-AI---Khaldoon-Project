"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type SecretStatus = {
  configured: boolean;
  source: "file" | "env" | "dev" | null;
  fresh: boolean;
  age_seconds: number | null;
  max_age_seconds: number | null;
};
type StatusResponse = {
  manager: { kind: string; application_connected: boolean; values_exposed: boolean };
  secrets: Record<"reviewer_proxy" | "openrouter" | "groq", SecretStatus>;
};

const LABELS = {
  reviewer_proxy: ["Reviewer signing", "Authenticates the workbench to the governed gate API."],
  openrouter: ["OpenRouter", "Primary model-provider credential."],
  groq: ["Groq", "Fallback model-provider credential."],
} as const;

function duration(seconds: number | null) {
  if (seconds === null) return "not available";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function SecretsAdmin() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/gw/admin/secrets/status", { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || response.statusText);
      setStatus(body as StatusResponse);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5" data-testid="secrets-admin">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wide text-(--color-muted)">
            <span className="rounded-full border border-(--color-border) px-2 py-0.5">Admin</span>
            <span className="rounded-full border border-(--color-border) px-2 py-0.5">OpenBao boundary</span>
          </div>
          <h1 className="text-xl font-semibold">Secrets &amp; providers</h1>
          <p className="max-w-2xl text-sm text-(--color-muted)">
            Tanaghom receives materialized files from OpenBao. It never receives an OpenBao token,
            and this page never displays secret values, paths, hashes, or login credentials.
          </p>
        </div>
        <div className="flex gap-2">
          <Link href="/" className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs hover:bg-(--color-elevated)">Back to runs</Link>
          <button type="button" onClick={() => { void load(); }} disabled={busy}
            className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs hover:bg-(--color-elevated) disabled:opacity-50">
            {busy ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div data-testid="secrets-admin-error" className="rounded-lg border border-(--color-danger) bg-(--color-danger-soft) px-3 py-2 text-sm">
          {error}
        </div>
      )}

      <section className="grid gap-3 md:grid-cols-3">
        {status && (Object.keys(LABELS) as Array<keyof typeof LABELS>).map((key) => {
          const item = status.secrets[key];
          const ready = item.configured && item.fresh;
          return (
            <article key={key} data-testid={`secret-status-${key}`}
              className="rounded-xl border border-(--color-border) bg-(--color-card) p-4 shadow-(--shadow-sm)">
              <div className="flex items-center justify-between gap-2">
                <span aria-hidden className="flex size-8 items-center justify-center rounded-lg bg-(--color-accent-soft)">◆</span>
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${ready
                  ? "bg-(--color-ok-soft) text-(--color-ok)"
                  : "bg-(--color-danger-soft) text-(--color-danger)"}`}>
                  {ready ? "materialized" : "attention"}
                </span>
              </div>
              <h2 className="mt-3 font-semibold">{LABELS[key][0]}</h2>
              <p className="mt-1 min-h-10 text-xs text-(--color-muted)">{LABELS[key][1]}</p>
              <dl className="mt-3 space-y-2 border-t border-(--color-border-subtle) pt-3 text-xs">
                <div className="flex justify-between gap-3"><dt className="text-(--color-muted)">Source</dt><dd className="font-mono">{item.source || "none"}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-(--color-muted)">Materialized age</dt><dd>{duration(item.age_seconds)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-(--color-muted)">Freshness limit</dt><dd>{duration(item.max_age_seconds)}</dd></div>
              </dl>
            </article>
          );
        })}
        {!status && !error && [0, 1, 2].map((n) => (
          <div key={n} className="h-52 animate-pulse rounded-xl border border-(--color-border) bg-(--color-card)" />
        ))}
      </section>

      <p className="text-xs text-(--color-muted)" data-testid="secret-status-scope">
        Materialized means the runtime file is valid and fresh. It does not prove that the external
        provider currently accepts the credential or that a model route is operational.
      </p>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-(--color-ok) bg-(--color-ok-soft) p-4">
          <h2 className="font-semibold">Application boundary</h2>
          <p className="mt-2 text-sm text-(--color-muted)">
            Gate and workbench can use only the exact files published by root-owned host materializers.
            They cannot browse OpenBao, mint tokens, change policies, or retrieve sibling secrets.
          </p>
        </div>
        <div className="rounded-xl border border-(--color-warn) bg-(--color-warn-soft) p-4">
          <h2 className="font-semibold">Native OpenBao administration</h2>
          <p className="mt-2 text-sm text-(--color-muted)">
            Secret writes, policy changes, and auth operations stay in OpenBao&apos;s audited native UI.
            Its VPS listener remains loopback-only and is reached through a separate SSH tunnel.
          </p>
          <a href="http://127.0.0.1:13200/ui/" target="_blank" rel="noreferrer"
            className="mt-3 inline-flex rounded-md border border-(--color-border-strong) px-3 py-1.5 text-xs font-medium hover:bg-(--color-elevated)">
            Open local OpenBao tunnel
          </a>
        </div>
      </section>
    </div>
  );
}
