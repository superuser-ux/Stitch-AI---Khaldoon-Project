"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type Binding = {
  identity_id: string;
  issuer: string;
  subject: string;
  principal_id: string;
  email: string | null;
  active: boolean;
  principal_display_name_en: string | null;
  principal_active: boolean;
};
type Principal = { principal_id: string; display_name_en: string | null };
type BindingList = { bindings: Binding[]; total: number };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/gw${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

export function IdentityAdmin() {
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [principals, setPrincipals] = useState<Principal[]>([]);
  const [issuer, setIssuer] = useState("");
  const [subject, setSubject] = useState("");
  const [principalId, setPrincipalId] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    const [bindingList, users, runtime] = await Promise.all([
      request<BindingList>("/identity/bindings?limit=100&offset=0"),
      request<Principal[]>("/principals?kind=user&active=true&module=content"),
      fetch("/api/runtime", { cache: "no-store" }).then((response) => response.json()),
    ]);
    setBindings(bindingList.bindings);
    setPrincipals(users);
    setIssuer(runtime.issuer || "");
  }

  useEffect(() => { load().catch((failure) => setError(String(failure.message || failure))); }, []);

  async function mutate(path: string, body: object, success: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      setNotice(success);
      await load();
    } catch (failure) {
      setError(String(failure instanceof Error ? failure.message : failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5" data-testid="identity-admin">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-(--color-muted)">IAM administration</p>
          <h1 className="mt-1 text-xl font-semibold">Sign-in connections</h1>
          <p className="mt-2 max-w-3xl text-sm text-(--color-muted)">
            Connect a verified external identity to an existing Tanaghom human principal. This never
            creates a principal or grants roles, AgentRep ownership, capabilities, assignments, or approvals.
          </p>
        </div>
        <Link href="/" className="rounded-md border border-(--color-border) px-3 py-1.5 text-sm">Back to workbench</Link>
      </div>

      {error && <div className="rounded-md border border-(--color-danger) bg-(--color-danger-soft) p-3 text-sm" data-testid="identity-admin-error">{error}</div>}
      {notice && <div className="rounded-md border border-(--color-success) p-3 text-sm" data-testid="identity-admin-notice">{notice}</div>}

      <section className="rounded-xl border border-(--color-border) bg-(--color-panel) p-4">
        <h2 className="font-semibold">Connect identity</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-(--color-muted)">Provider issuer
            <input value={issuer} readOnly className="mt-1 w-full rounded-md border border-(--color-border) bg-(--color-sunken) px-3 py-2 font-mono text-sm" data-testid="binding-issuer" />
          </label>
          <label className="text-xs text-(--color-muted)">Provider subject (exact, case-sensitive)
            <input value={subject} onChange={(event) => setSubject(event.target.value)} className="mt-1 w-full rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-2 text-sm" data-testid="binding-subject" />
          </label>
          <label className="text-xs text-(--color-muted)">Tanaghom human principal
            <select value={principalId} onChange={(event) => setPrincipalId(event.target.value)} className="mt-1 w-full rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-2 text-sm" data-testid="binding-principal">
              <option value="">Choose a principal…</option>
              {principals.map((principal) => <option key={principal.principal_id} value={principal.principal_id}>{principal.display_name_en || principal.principal_id}</option>)}
            </select>
          </label>
          <label className="text-xs text-(--color-muted)">Email note (not used for access)
            <input value={email} onChange={(event) => setEmail(event.target.value)} className="mt-1 w-full rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-2 text-sm" data-testid="binding-email" />
          </label>
        </div>
        <button
          type="button"
          disabled={busy || !issuer || !subject || !principalId}
          onClick={() => { void mutate("/identity/bindings", { issuer, subject, principal_id: principalId, email: email || null }, "Sign-in identity connected."); }}
          className="mt-4 rounded-md bg-(--color-accent) px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          data-testid="binding-create"
        >
          Connect identity
        </button>
      </section>

      <section className="rounded-xl border border-(--color-border) bg-(--color-panel) p-4">
        <h2 className="font-semibold">Existing connections ({bindings.length})</h2>
        <div className="mt-3 flex flex-col gap-2">
          {bindings.length === 0 && <p className="text-sm text-(--color-muted)">No sign-in identities are connected.</p>}
          {bindings.map((binding) => (
            <div key={binding.identity_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-(--color-border-subtle) p-3 text-sm" data-testid={`binding-${binding.subject}`}>
              <span className={`rounded-full border px-2 py-0.5 text-xs ${binding.active ? "border-(--color-success)" : "border-(--color-border) text-(--color-muted)"}`}>{binding.active ? "connected" : "disconnected"}</span>
              <code className="text-xs">{binding.subject}</code>
              <span className="text-(--color-muted)">→</span>
              <strong>{binding.principal_display_name_en || binding.principal_id}</strong>
              {!binding.principal_active && <span className="text-xs text-(--color-danger)">principal inactive</span>}
              <button
                type="button"
                disabled={busy}
                onClick={() => { void mutate(`/identity/bindings/${binding.identity_id}/${binding.active ? "deactivate" : "reactivate"}`, {}, binding.active ? "Connection disconnected." : "Connection reconnected."); }}
                className="ms-auto rounded-md border border-(--color-border) px-3 py-1 text-xs"
                data-testid={`binding-toggle-${binding.subject}`}
              >
                {binding.active ? "Disconnect" : "Reconnect"}
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
