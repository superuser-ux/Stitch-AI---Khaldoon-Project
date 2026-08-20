"use client";

// #443 — the ONE read-only V2 Settings-truth surface. It renders the bounded safe projection served
// by the gate API (`GET /admin/settings/truth`, engine.load_config → settings_truth.project) and
// interprets NOTHING: provider kind, a safe endpoint identity, model identity under existing
// route-role labels, presence/type-only secret references, and configured-state-only availability.
// It never displays a secret value, a credential env-var name, or a URL query/fragment/userinfo, and
// it makes no availability claim stronger than "configured". Generation/provenance is absent in the
// authority, so it is shown as unavailable rather than invented. The surface mutates nothing.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { readJson, ReadError } from "@/lib/read-model";

type AvailabilityState = "configured" | "unknown";
type Availability = { state: AvailabilityState };
type SecretReference = { required: boolean; type: string | null };
type Provider = {
  key: string;
  kind: string | null;
  endpoint: string | null;
  secret_reference: SecretReference;
  availability: Availability;
};
type RouteHop = { provider: string | null; model: string | null; availability: Availability };
type RouteRole = { role: string; primary: RouteHop | null; fallback: RouteHop[] };
type SettingsTruth = {
  authority: string;
  provenance: { available: boolean };
  providers: Provider[];
  routes: RouteRole[];
};

function AvailabilityBadge({ availability }: { availability: Availability }) {
  const configured = availability.state === "configured";
  return (
    <span
      data-testid="availability-state"
      data-state={availability.state}
      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${configured
        ? "bg-(--color-ok-soft) text-(--color-ok)"
        : "bg-(--color-warn-soft) text-(--color-warn)"}`}
    >
      {configured ? "configured" : "unknown"}
    </span>
  );
}

function Hop({ hop, label }: { hop: RouteHop | null; label: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-(--color-border-subtle) pt-2 text-xs first:border-0 first:pt-0">
      <span className="text-(--color-muted)">{label}</span>
      {hop ? (
        <span className="flex items-center gap-2">
          <span className="font-mono">{hop.provider ?? "—"}</span>
          <span className="text-(--color-muted)">/</span>
          <span className="font-mono">{hop.model ?? "—"}</span>
          <AvailabilityBadge availability={hop.availability} />
        </span>
      ) : (
        <span className="text-(--color-muted)">not configured</span>
      )}
    </div>
  );
}

export function SettingsAdmin() {
  const [truth, setTruth] = useState<SettingsTruth | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const body = await readJson<SettingsTruth>("/gw/admin/settings/truth");
      setTruth(body);
    } catch (e) {
      // ReadError already carries the server's typed reason (or a truthful transport failure).
      setError(e instanceof ReadError ? e.message : String(e instanceof Error ? e.message : e));
      setTruth(null);
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const empty = truth !== null && truth.providers.length === 0 && truth.routes.length === 0;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5" data-testid="settings-admin">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-[10px] font-medium uppercase tracking-wide text-(--color-muted)">
            <span className="rounded-full border border-(--color-border) px-2 py-0.5">Admin</span>
            <span className="rounded-full border border-(--color-border) px-2 py-0.5">Configuration truth</span>
          </div>
          <h1 className="text-xl font-semibold">Providers, models &amp; routes</h1>
          <p className="max-w-2xl text-sm text-(--color-muted)">
            A read-only view of the governed provider/model/route configuration. It never displays
            secret values, credential names, or URL credentials, and it makes no availability claim
            beyond what the configuration records.
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
        <div data-testid="settings-admin-error" className="rounded-lg border border-(--color-danger) bg-(--color-danger-soft) px-3 py-2 text-sm">
          Configuration truth is unavailable: {error}
        </div>
      )}

      {truth && (
        <p data-testid="settings-authority" className="text-xs text-(--color-muted)">
          Source of truth: <span className="font-mono">{truth.authority}</span>.{" "}
          {truth.provenance.available
            ? "Configuration generation/provenance identity is available."
            : "Configuration generation/provenance identity is not defined by this authority and is omitted."}
        </p>
      )}

      {empty && (
        <div data-testid="settings-admin-empty" className="rounded-lg border border-(--color-border) bg-(--color-card) px-3 py-6 text-center text-sm text-(--color-muted)">
          No providers or routes are configured.
        </div>
      )}

      {truth && truth.providers.length > 0 && (
        <section className="grid gap-3 md:grid-cols-2 lg:grid-cols-3" data-testid="settings-providers">
          {truth.providers.map((p) => (
            <article key={p.key} data-testid={`provider-${p.key}`}
              className="rounded-xl border border-(--color-border) bg-(--color-card) p-4 shadow-(--shadow-sm)">
              <div className="flex items-center justify-between gap-2">
                <h2 className="font-semibold">{p.key}</h2>
                <AvailabilityBadge availability={p.availability} />
              </div>
              <dl className="mt-3 space-y-2 border-t border-(--color-border-subtle) pt-3 text-xs">
                <div className="flex justify-between gap-3"><dt className="text-(--color-muted)">Kind</dt><dd className="font-mono">{p.kind ?? "—"}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-(--color-muted)">Endpoint</dt><dd data-testid={`provider-endpoint-${p.key}`} className="truncate font-mono" title={p.endpoint ?? undefined}>{p.endpoint ?? "—"}</dd></div>
                <div className="flex justify-between gap-3">
                  <dt className="text-(--color-muted)">Credential</dt>
                  <dd data-testid={`provider-secret-${p.key}`}>
                    {p.secret_reference.required
                      ? `required (${p.secret_reference.type})`
                      : "not required"}
                  </dd>
                </div>
              </dl>
            </article>
          ))}
        </section>
      )}

      {truth && truth.routes.length > 0 && (
        <section className="grid gap-3 md:grid-cols-2" data-testid="settings-routes">
          {truth.routes.map((r) => (
            <article key={r.role} data-testid={`route-${r.role}`}
              className="rounded-xl border border-(--color-border) bg-(--color-card) p-4 shadow-(--shadow-sm)">
              <h2 className="font-semibold">{r.role}</h2>
              <p className="mt-1 text-[11px] uppercase tracking-wide text-(--color-muted)">Route role</p>
              <div className="mt-3 space-y-2">
                <Hop hop={r.primary} label="Primary" />
                {r.fallback.map((h, i) => (
                  <Hop key={i} hop={h} label={`Fallback ${i + 1}`} />
                ))}
              </div>
            </article>
          ))}
        </section>
      )}

      {!truth && !error && (
        <section className="grid gap-3 md:grid-cols-3" data-testid="settings-admin-loading">
          {[0, 1, 2].map((n) => (
            <div key={n} className="h-40 animate-pulse rounded-xl border border-(--color-border) bg-(--color-card)" />
          ))}
        </section>
      )}

      <p className="text-xs text-(--color-muted)" data-testid="settings-scope">
        Configured means the entry exists in the governed configuration. It does not prove that a
        provider currently accepts its credential or that a route is operational — this surface runs no
        health check, credential validation, network probe, or model discovery.
      </p>
    </div>
  );
}
