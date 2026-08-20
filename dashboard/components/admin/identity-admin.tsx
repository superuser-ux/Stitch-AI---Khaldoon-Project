"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Link2, Link2Off, RefreshCcw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

// #194 (#172 S2) — governed sign-in-link (identity-binding) administration. Bounded internal
// surface over server truth: list / connect / disconnect / reconnect only. Client-side visibility
// is NEVER enforcement — every operation is re-authorized server-side against the persisted
// policy_admin contract, and all lifecycle rules (insert-only, same-tuple reactivation, CAS,
// self-lockout) live in the engine. Copy follows #186: plain words, no auth jargon.

const GW = "/gw";
async function jget<T>(path: string): Promise<T> {
  const res = await fetch(`${GW}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}
async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${GW}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

type Binding = {
  identity_id: string; issuer: string; subject: string; principal_id: string;
  email: string | null; display_name: string | null; active: boolean;
  principal_display_name_en: string | null; principal_active: boolean;
  updated_by: string | null;
};
type BindingList = { bindings: Binding[]; total: number; limit: number; offset: number };
type Principal = { principal_id: string; kind: string; display_name_en: string | null };

const EMPTY_FORM = { issuer: "", subject: "", principal_id: "", email: "", display_name: "" };

export function IdentityAdmin() {
  const [list, setList] = useState<BindingList | null>(null);
  const [principals, setPrincipals] = useState<Principal[]>([]);
  const [offset, setOffset] = useState(0);
  const [issuer, setIssuer] = useState<string | null>(null);   // server-declared canonical issuer
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [confirming, setConfirming] = useState<string | null>(null);   // identity_id pending confirm
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [denied, setDenied] = useState(false);

  const PAGE = 25;
  const load = useCallback(async () => {
    try {
      // #195 review (least privilege): authorization is decided by the bindings read FIRST; the
      // eligible-principal selection dataset is requested ONLY after that succeeds — a non-admin
      // never requests or receives it.
      const bindings = await jget<BindingList>(`/identity/bindings?limit=${PAGE}&offset=${offset}`);
      setList(bindings);
      setDenied(false);
      const [users, rt] = await Promise.all([
        jget<Principal[]>("/principals?kind=user&active=true&module=content"),
        fetch("/api/runtime", { cache: "no-store" }).then((r) => r.json()).catch(() => null),
      ]);
      setPrincipals(users);
      setIssuer(rt?.issuer || null);
    } catch (e) {
      // truthful: this surface simply isn't available without the admin authority (server-decided)
      if (String(e).includes("may not administer")) setDenied(true);
      else setError(String(e instanceof Error ? e.message : e));
    }
  }, [offset]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    setBusy(true); setError(""); setNotice("");
    try {
      await fn();
      setNotice(okMsg);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
      setConfirming(null);
      await load().catch(() => {});   // always refetch server truth after a mutation attempt
    }
  };

  const create = () => run(async () => {
    await jpost("/identity/bindings", {
      // issuer comes from server truth when this server knows its sign-in provider; subject is
      // sent EXACTLY as entered (opaque + case-sensitive — the server rejects invalid input,
      // it never repairs it)
      issuer: issuer ?? form.issuer,
      subject: form.subject,
      principal_id: form.principal_id,
      email: form.email.trim() || null, display_name: form.display_name.trim() || null,
    });
    setForm({ ...EMPTY_FORM });
  }, "Sign-in identity connected.");

  const setActive = (b: Binding, active: boolean) => run(async () => {
    await jpost(`/identity/bindings/${b.identity_id}/${active ? "reactivate" : "deactivate"}`);
  }, active ? "Sign-in link reconnected. The person must sign in again to use it." : "Sign-in link disconnected. Their current session ends on their next action.");

  if (denied) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <div data-testid="identity-admin-denied" className="rounded-2xl border border-border/80 bg-card p-6">
          <h1 className="text-lg font-semibold">Sign-in connections</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            This page is only available to administrators. Your account doesn&apos;t have that
            access.
          </p>
          <Button asChild variant="outline" className="mt-4"><Link href="/"><ArrowLeft />Back to operations</Link></Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8" data-testid="identity-admin">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge variant="outline">Admin</Badge>
              <Badge variant="secondary">Sign-in connections</Badge>
            </div>
            <h1 className="text-2xl font-semibold">Sign-in connections</h1>
            {/* #194 required statement (#186-compliant wording) */}
            <p className="max-w-2xl text-sm text-muted-foreground">
              Connecting a sign-in identity links it to an existing Tanaghom user. It does not
              create the user, grant roles, change assignments, disable the external sign-in
              account, or deactivate the Tanaghom user.
            </p>
          </div>
          <div className="flex gap-2">
            <Button asChild variant="outline"><Link href="/"><ArrowLeft />Back to operations</Link></Button>
            <Button variant="outline" onClick={() => { void load(); }} disabled={busy}><RefreshCcw />Refresh</Button>
          </div>
        </div>

        {error && <div data-testid="identity-admin-error" className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm">{error}</div>}
        {notice && <div data-testid="identity-admin-notice" className="rounded-lg border border-success/40 bg-success/10 px-3 py-2 text-sm">{notice}</div>}

        <section className="rounded-2xl border border-border/80 bg-card p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Connect a sign-in identity</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs">
              <span className="text-muted-foreground">Sign-in provider</span>
              {issuer ? (
                <div data-testid="binding-issuer-fixed" className="mt-1 w-full rounded-lg border bg-muted/40 px-3 py-2 font-mono text-sm">{issuer}</div>
              ) : (
                <input data-testid="binding-issuer" className="mt-1 w-full rounded-lg border bg-background px-3 py-2 text-sm" value={form.issuer} maxLength={512}
                  onChange={(e) => setForm((f) => ({ ...f, issuer: e.target.value }))} placeholder="https://… (exact, no trailing slash)" />
              )}
            </label>
            <label className="text-xs">
              <span className="text-muted-foreground">Account identifier (exact, case-sensitive)</span>
              <input data-testid="binding-subject" className="mt-1 w-full rounded-lg border bg-background px-3 py-2 text-sm" value={form.subject} maxLength={512}
                onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))} />
            </label>
            <label className="text-xs">
              <span className="text-muted-foreground">Tanaghom user</span>
              <select data-testid="binding-principal" className="mt-1 w-full rounded-lg border bg-background px-3 py-2 text-sm" value={form.principal_id}
                onChange={(e) => setForm((f) => ({ ...f, principal_id: e.target.value }))}>
                <option value="">Choose a user…</option>
                {principals.map((p) => (
                  <option key={p.principal_id} value={p.principal_id}>{p.display_name_en || p.principal_id} ({p.principal_id})</option>
                ))}
              </select>
            </label>
            <label className="text-xs">
              <span className="text-muted-foreground">Email (note only — not used for matching or access)</span>
              <input data-testid="binding-email" className="mt-1 w-full rounded-lg border bg-background px-3 py-2 text-sm" value={form.email} maxLength={320}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </label>
          </div>
          <Button data-testid="binding-create" className="mt-4" disabled={busy || !(issuer ?? form.issuer) || form.subject.length === 0 || !form.principal_id} onClick={create}>
            <Link2 />Connect sign-in identity
          </Button>
        </section>

        <section className="rounded-2xl border border-border/80 bg-card p-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Existing connections {list ? `(${list.total})` : ""}
          </h2>
          <div className="mt-3 flex flex-col gap-2">
            {list?.bindings.length === 0 && <p className="text-sm text-muted-foreground">No sign-in identities are connected yet.</p>}
            {list?.bindings.map((b) => (
              <div key={b.identity_id} data-testid={`binding-${b.subject}`} className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-background/70 px-3 py-2 text-sm">
                <Badge variant={b.active ? "success" : "outline"} data-testid={`binding-status-${b.subject}`}>
                  {b.active ? "connected" : "disconnected"}
                </Badge>
                <span className="font-mono text-xs">{b.subject}</span>
                <span className="text-xs text-muted-foreground">at {b.issuer}</span>
                <span aria-hidden>→</span>
                <span className="font-medium">{b.principal_display_name_en || b.principal_id}</span>
                {!b.principal_active && <Badge variant="warning">Tanaghom user inactive</Badge>}
                {b.email && <span className="text-xs text-muted-foreground">({b.email})</span>}
                <span className="ml-auto flex items-center gap-2">
                  {confirming === b.identity_id ? (
                    <>
                      <span className="text-xs text-muted-foreground">
                        {b.active
                          ? "Disconnect this sign-in? The person keeps their Tanaghom user and external account, but this sign-in stops working on their next action."
                          : "Reconnect this sign-in? The person must sign in again before it works."}
                      </span>
                      <Button size="sm" variant={b.active ? "destructive" : "success"} data-testid={`binding-confirm-${b.subject}`} disabled={busy}
                        onClick={() => setActive(b, !b.active)}>Confirm</Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                    </>
                  ) : (
                    <Button size="sm" variant="outline" data-testid={`binding-toggle-${b.subject}`} disabled={busy}
                      onClick={() => setConfirming(b.identity_id)}>
                      {b.active ? <><Link2Off />Disconnect</> : <><Link2 />Reconnect</>}
                    </Button>
                  )}
                </span>
              </div>
            ))}
          </div>
          {list && list.total > list.limit && (
            <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              <Button size="sm" variant="outline" data-testid="bindings-prev" disabled={busy || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - list.limit))}>Previous</Button>
              <span data-testid="bindings-page-info">
                {offset + 1}–{Math.min(offset + list.limit, list.total)} of {list.total}
              </span>
              <Button size="sm" variant="outline" data-testid="bindings-next" disabled={busy || offset + list.limit >= list.total}
                onClick={() => setOffset(offset + list.limit)}>Next</Button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
