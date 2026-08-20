"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Archive, ArrowLeft, GitBranch, Plus, RefreshCcw, RotateCcw, Save, Shield, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type MethodologyVersion = {
  version_id: string;
  version_no: number;
  status: string;
  source: string;
  notes: string | null;
  source_digest: string | null;
  source_manifest: { files?: { path: string; sha256: string }[] };
  counts: { pillars: number; lenses: number; hook_types: number; hcs: number };
};
type MethodologySummary = {
  methodology_id: string;
  methodology_key: string;
  name: string;
  description: string | null;
  active_version_id: string | null;
  versions: {
    version_id: string;
    version_no: number;
    status: string;
    source: string;
    notes: string | null;
    pillar_count: number;
    lens_count: number;
    hook_type_count: number;
    hcs_count: number;
  }[];
};
type MethodologyCatalog = {
  can_administer: boolean;
  methodologies: MethodologySummary[];
  active_version: MethodologyVersion | null;
};
type Platform = {
  platform_id: string;
  platform_key: string;
  name: string;
  channel_role: string;
  description: string | null;
  active: boolean;
};
type FormatFrameworkRules = {
  seed_source?: string;
  framework_id?: string;
  framework_name?: string;
  framework_status?: string;
  framework_summary?: string;
  mapping_note?: string;
  reference_docs?: string[];
  principles?: string[];
  structure?: { step: string; label: string; guidance: string; constraint?: string }[];
  closing_sections?: { label: string; guidance: string }[];
  dos?: string[];
  donts?: string[];
  constraints?: Record<string, string | number | boolean>;
};
type FormatVersion = {
  version_id: string;
  version_no: number;
  status: string;
  source: string;
  use_case: string | null;
  lens_fit: string[];
  production_notes: string | null;
  production_rules?: FormatFrameworkRules | null;
  platform_targets: string[];
};
type FormatRow = {
  content_format_id: string;
  format_key: string;
  name: string;
  description: string | null;
  active: boolean;
  lifecycle_status?: string;
  archived_at?: string | null;
  archived_by?: string | null;
  active_version: FormatVersion | null;
  versions: FormatVersion[];
};
type ContentFormatCatalog = {
  can_administer: boolean;
  platforms: Platform[];
  formats: FormatRow[];
};
type FormatDraft = {
  use_case: string;
  lens_fit: string;
  production_notes: string;
  production_rules: string;
  platform_targets: string;
};
type FormatCatalogDraft = {
  format_key: string;
  name: string;
  description: string;
};
type NewFormatState = {
  format_key: string;
  name: string;
  description: string;
  use_case: string;
  lens_fit: string;
  production_notes: string;
  production_rules: string;
  platform_targets: string;
};

const GW = "/gw";

async function jget<T>(path: string): Promise<T> {
  const res = await fetch(path.startsWith("/api/") ? path : `${GW}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${GW}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

async function jput<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${GW}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

async function jdel<T>(path: string): Promise<T> {
  const res = await fetch(`${GW}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function csv(values: string[]) {
  return values.join(", ");
}

function csvToList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function prettyJson(value: unknown) {
  return JSON.stringify(value || {}, null, 2);
}

const EMPTY_NEW_FORMAT: NewFormatState = {
  format_key: "",
  name: "",
  description: "",
  use_case: "",
  lens_fit: "",
  production_notes: "",
  production_rules: "{}",
  platform_targets: "instagram",
};

function titleCaseConstraint(key: string) {
  return key.replace(/_/g, " ");
}

function FrameworkPanel({ rules }: { rules?: FormatFrameworkRules | null }) {
  // #177 — an operator must be able to tell configured framework vs missing client data vs system
  // fallback at a glance, so the panel never renders nothing silently.
  const isLegacy = rules?.framework_status === "legacy_carry_forward";
  const hasStructure = Boolean(rules?.structure?.length);
  if (!rules?.framework_name && !isLegacy) {
    return (
      <div className="space-y-2 rounded-lg border border-dashed bg-muted/20 p-3" data-testid="framework-missing">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">Framework</Badge>
          <Badge variant="warning">No framework configured — writer uses the generic fallback structure</Badge>
        </div>
        {rules?.mapping_note && <p className="text-sm text-muted-foreground">{rules.mapping_note}</p>}
      </div>
    );
  }
  const constraints = Object.entries(rules?.constraints || {});

  return (
    <div className="space-y-3 rounded-lg border border-dashed bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">Framework</Badge>
        {rules.framework_name && <span className="font-medium">{rules.framework_name}</span>}
        {rules.framework_id && <Badge variant="outline">{rules.framework_id}</Badge>}
        {rules.seed_source && <Badge variant="outline">{rules.seed_source}</Badge>}
        {/* #177 — configured vs legacy vs incomplete, stated explicitly */}
        {isLegacy ? (
          <Badge variant="warning" data-testid="framework-legacy">Legacy carry-forward — no client framework configured</Badge>
        ) : hasStructure ? (
          <Badge variant="success" data-testid="framework-structure-count">{rules.structure!.length}-step structure configured</Badge>
        ) : (
          <Badge variant="warning" data-testid="framework-structure-missing">No structure configured — writer uses the generic fallback</Badge>
        )}
      </div>

      {rules.framework_summary && <p className="text-sm text-muted-foreground">{rules.framework_summary}</p>}
      {rules.mapping_note && <p className="text-sm text-muted-foreground">{rules.mapping_note}</p>}

      {constraints.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
          {constraints.map(([key, value]) => <span key={key}>{titleCaseConstraint(key)}: {String(value)}</span>)}
        </div>
      )}

      {rules.structure?.length ? (
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Structure</div>
          <div className="space-y-2">
            {rules.structure.map((step) => (
              <div key={step.step} className="rounded-md border bg-background/70 p-2">
                <div className="text-sm font-medium">{step.label}</div>
                <div className="text-sm text-muted-foreground">{step.guidance}</div>
                {step.constraint && <div className="mt-1 text-xs text-muted-foreground">{step.constraint}</div>}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {rules.principles?.length ? (
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Core principles</div>
          <div className="flex flex-wrap gap-2">
            {rules.principles.map((item) => <Badge key={item} variant="outline" className="whitespace-normal text-left">{item}</Badge>)}
          </div>
        </div>
      ) : null}

      {rules.closing_sections?.length ? (
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Closing sections</div>
          <div className="space-y-2">
            {rules.closing_sections.map((section) => (
              <div key={section.label} className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{section.label}:</span> {section.guidance}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {(rules.dos?.length || rules.donts?.length) && (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Do</div>
            <div className="space-y-1">
              {(rules.dos || []).map((item) => <div key={item} className="text-sm text-muted-foreground">{item}</div>)}
            </div>
          </div>
          <div className="space-y-2">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Avoid</div>
            <div className="space-y-1">
              {(rules.donts || []).map((item) => <div key={item} className="text-sm text-muted-foreground">{item}</div>)}
            </div>
          </div>
        </div>
      )}

      {rules.reference_docs?.length ? (
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">Reference docs</div>
          <div className="space-y-1">
            {rules.reference_docs.map((path) => <div key={path} className="font-mono text-xs text-muted-foreground">{path}</div>)}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// #184 — read model of the DB-managed topic-repetition policy (see GET /repetition-policy)
type RepetitionPolicyCatalog = {
  policy: {
    enabled: boolean; scope: string; similarity_threshold: number; max_regenerations: number;
    repeat_modes: Record<string, boolean>; source: string; updated_by: string | null;
  };
  repeat_modes_supported: string[];
  can_administer: boolean;
};

export function MethodologyAdmin() {
  const [reviewer, setReviewer] = useState("khal");
  const [repetitionPolicy, setRepetitionPolicy] = useState<RepetitionPolicyCatalog | null>(null);
  const [catalog, setCatalog] = useState<MethodologyCatalog | null>(null);
  const [formatCatalog, setFormatCatalog] = useState<ContentFormatCatalog | null>(null);
  const [methodologyNotes, setMethodologyNotes] = useState<Record<string, string>>({});
  const [formatCatalogDrafts, setFormatCatalogDrafts] = useState<Record<string, FormatCatalogDraft>>({});
  const [formatDrafts, setFormatDrafts] = useState<Record<string, FormatDraft>>({});
  const [newFormat, setNewFormat] = useState<NewFormatState>(EMPTY_NEW_FORMAT);
  const [busy, setBusy] = useState<string>("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [methodologies, formats, reviewerRes, repetition] = await Promise.all([
      jget<MethodologyCatalog>("/methodologies"),
      jget<ContentFormatCatalog>("/content-formats"),
      jget<{ reviewer: string }>("/api/reviewer"),
      // #184 — minimal truthful disclosure of the ACTIVE managed repetition policy (read-only here)
      jget<RepetitionPolicyCatalog>("/repetition-policy").catch(() => null),
    ]);
    setCatalog(methodologies);
    setFormatCatalog(formats);
    setReviewer(reviewerRes.reviewer);
    setRepetitionPolicy(repetition);
    setMethodologyNotes((current) => {
      const next = { ...current };
      for (const methodology of methodologies.methodologies) {
        for (const version of methodology.versions) {
          if (version.status === "draft" && next[version.version_id] === undefined) {
            next[version.version_id] = version.notes || "";
          }
        }
      }
      return next;
    });
    setFormatCatalogDrafts((current) => {
      const next = { ...current };
      for (const format of formats.formats) {
        next[format.content_format_id] = {
          format_key: format.format_key,
          name: format.name,
          description: format.description || "",
        };
      }
      return next;
    });
    setFormatDrafts((current) => {
      const next = { ...current };
      for (const format of formats.formats) {
        const draft = format.versions.find((version) => version.status === "draft");
        if (draft && !next[draft.version_id]) {
          next[draft.version_id] = {
            use_case: draft.use_case || "",
            lens_fit: csv(draft.lens_fit || []),
            production_notes: draft.production_notes || "",
            production_rules: prettyJson(draft.production_rules || {}),
            platform_targets: csv(draft.platform_targets || []),
          };
        }
      }
      return next;
    });
  }, []);

  useEffect(() => {
    load().catch((e) => setError(String(e)));
  }, [load]);

  const run = async (token: string, fn: () => Promise<void>) => {
    setBusy(token);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  const methodologies = catalog?.methodologies || [];
  const active = catalog?.active_version;
  const methodology = methodologies[0] || null;

  const createMethodologyDraft = async () => run("methodology:create", async () => {
    if (!methodology) return;
    const created = await jpost<MethodologyVersion>(`/methodologies/${methodology.methodology_key}/versions/draft`, {});
    setMessage(`Created methodology draft v${created.version_no}.`);
    await load();
  });

  const saveMethodologyDraft = async (versionId: string) => run(`methodology:save:${versionId}`, async () => {
    await jput(`/methodology-versions/${versionId}`, { notes: methodologyNotes[versionId] || "" });
    setMessage("Methodology draft saved.");
    await load();
  });

  const activateMethodologyDraft = async (versionId: string) => run(`methodology:activate:${versionId}`, async () => {
    await jpost(`/methodology-versions/${versionId}/activate`, {});
    setMessage("Methodology version activated.");
    await load();
  });

  const createFormatDraft = async (formatKey: string) => run(`format:create:${formatKey}`, async () => {
    const created = await jpost<FormatVersion>(`/content-formats/${formatKey}/versions/draft`, {});
    setFormatDrafts((current) => ({
      ...current,
      [created.version_id]: {
        use_case: created.use_case || "",
        lens_fit: csv(created.lens_fit || []),
        production_notes: created.production_notes || "",
        production_rules: prettyJson(created.production_rules || {}),
        platform_targets: csv(created.platform_targets || []),
      },
    }));
    setMessage(`Created content-type draft v${created.version_no}.`);
    await load();
  });

  const createContentType = async () => run("format:new", async () => {
    const created = await jpost<FormatRow>("/content-formats", {
      format_key: newFormat.format_key,
      name: newFormat.name,
      description: newFormat.description,
      use_case: newFormat.use_case,
      lens_fit: csvToList(newFormat.lens_fit),
      production_notes: newFormat.production_notes,
      production_rules: JSON.parse(newFormat.production_rules || "{}"),
      platform_targets: csvToList(newFormat.platform_targets),
    });
    setNewFormat(EMPTY_NEW_FORMAT);
    setMessage(`Created content type ${created.name}.`);
    await load();
  });

  const saveFormatCatalog = async (contentFormatId: string) => run(`format:catalog:${contentFormatId}`, async () => {
    const draft = formatCatalogDrafts[contentFormatId];
    await jput(`/content-formats/${contentFormatId}`, {
      format_key: draft?.format_key || "",
      name: draft?.name || "",
      description: draft?.description || "",
    });
    setMessage("Content type details saved.");
    await load();
  });

  const saveFormatDraft = async (versionId: string) => run(`format:save:${versionId}`, async () => {
    const draft = formatDrafts[versionId];
    await jput(`/content-format-versions/${versionId}`, {
      use_case: draft?.use_case || "",
      lens_fit: csvToList(draft?.lens_fit || ""),
      production_notes: draft?.production_notes || "",
      production_rules: JSON.parse(draft?.production_rules || "{}"),
      platform_targets: csvToList(draft?.platform_targets || ""),
    });
    setMessage("Content-type draft saved.");
    await load();
  });

  const activateFormatDraft = async (versionId: string) => run(`format:activate:${versionId}`, async () => {
    await jpost(`/content-format-versions/${versionId}/activate`, {});
    setMessage("Content-type version activated.");
    await load();
  });

  const archiveFormat = async (contentFormatId: string) => run(`format:archive:${contentFormatId}`, async () => {
    await jpost(`/content-formats/${contentFormatId}/archive`, {});
    setMessage("Content type archived.");
    await load();
  });

  const restoreFormat = async (contentFormatId: string) => run(`format:restore:${contentFormatId}`, async () => {
    await jpost(`/content-formats/${contentFormatId}/restore`, {});
    setMessage("Content type restored.");
    await load();
  });

  const deleteFormat = async (contentFormatId: string, name: string) => {
    if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;
    await run(`format:delete:${contentFormatId}`, async () => {
      await jdel(`/content-formats/${contentFormatId}`);
      setMessage("Content type deleted.");
      await load();
    });
  };

  const resetFormatRegistry = async () => {
    if (!window.confirm("Reset the content-type registry and wipe current rounds, slots, approvals, scripts, and production state?")) return;
    await run("format:reset", async () => {
      await jpost("/content-formats/reset", { confirm_reset: true });
      setMessage("Content-type registry reset to the current bootstrap set.");
      await load();
    });
  };

  const flatMethodologyVersions = useMemo(
    () => methodologies.flatMap((item) => item.versions.map((version) => ({ ...version, methodology: item.name }))),
    [methodologies],
  );

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge variant="outline">Admin</Badge>
              <Badge variant="outline">{reviewer}</Badge>
              {catalog?.can_administer
                ? <Badge className="bg-success text-white hover:bg-success">can administer</Badge>
                : <Badge variant="outline">read only</Badge>}
            </div>
            <h1 className="text-2xl font-semibold">Methodology Admin</h1>
            <p className="text-sm text-muted-foreground">Versioned methodology and content-type control surface.</p>
            {/* #184 — minimal truthful disclosure of the ACTIVE topic-repetition policy: what the
                writer actually enforces right now, and where that policy comes from. Read-only
                surface; changes go through the authority-gated PUT /repetition-policy. */}
            {repetitionPolicy && (
              <div data-testid="repetition-policy" className="flex flex-wrap items-center gap-2 pt-1 text-xs text-muted-foreground">
                <Badge variant="secondary">Topic repetition policy</Badge>
                <span data-testid="repetition-policy-scope">
                  {repetitionPolicy.policy.enabled
                    ? `no same-topic reuse · scope: ${repetitionPolicy.policy.scope}`
                    : "dedup disabled"}
                </span>
                <span data-testid="repetition-policy-modes">
                  {Object.entries(repetitionPolicy.policy.repeat_modes).filter(([, v]) => v).length
                    ? `allowed repeat modes: ${Object.entries(repetitionPolicy.policy.repeat_modes).filter(([, v]) => v).map(([k]) => k.replace(/_/g, " ")).join(", ")}`
                    : "no repeat modes active"}
                </span>
                <Badge variant="outline" data-testid="repetition-policy-source">
                  {repetitionPolicy.policy.source === "managed"
                    ? `managed${repetitionPolicy.policy.updated_by ? ` · by ${repetitionPolicy.policy.updated_by}` : ""}`
                    : "production default"}
                </Badge>
              </div>
            )}
          </div>
          <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:flex-row sm:items-center">
            <Button asChild variant="outline" className="justify-center"><Link href="/"><ArrowLeft />Back to operations</Link></Button>
            <Button asChild variant="outline" className="justify-center"><Link href="/admin/workflows"><GitBranch />Workflow admin</Link></Button>
            <Button asChild variant="outline" className="justify-center"><Link href="/admin/identity"><GitBranch />Sign-in connections</Link></Button>
            {catalog?.can_administer && (
              <Button onClick={createMethodologyDraft} disabled={busy === "methodology:create"} className="justify-center">
                <GitBranch />{busy === "methodology:create" ? "Creating..." : "Clone active to draft"}
              </Button>
            )}
          </div>
        </div>

        {(message || error) && (
          <div className={`rounded-lg border px-4 py-3 text-sm ${error ? "border-destructive/40 text-destructive" : "border-success/40 text-success"}`}>
            {error || message}
          </div>
        )}

        <section className="grid gap-4 xl:grid-cols-[1.2fr,0.8fr]">
          <div className="space-y-4 rounded-xl border bg-card/50 p-4">
            <div>
              <h2 className="font-semibold">Active methodology version</h2>
              <p className="text-sm text-muted-foreground">The active methodology remains the backend canonical reference.</p>
            </div>
            {active ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">v{active.version_no}</Badge>
                  <Badge variant="secondary">{active.status}</Badge>
                  <Badge variant="outline">{active.source}</Badge>
                  {active.source_digest && <Badge variant="outline" className="font-mono">{active.source_digest.slice(0, 12)}</Badge>}
                </div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <div className="rounded-lg border bg-background/60 p-3"><div className="text-xs text-muted-foreground">Pillars</div><div className="text-2xl font-semibold">{active.counts.pillars}</div></div>
                  <div className="rounded-lg border bg-background/60 p-3"><div className="text-xs text-muted-foreground">Lenses</div><div className="text-2xl font-semibold">{active.counts.lenses}</div></div>
                  <div className="rounded-lg border bg-background/60 p-3"><div className="text-xs text-muted-foreground">Hook types</div><div className="text-2xl font-semibold">{active.counts.hook_types}</div></div>
                  <div className="rounded-lg border bg-background/60 p-3"><div className="text-xs text-muted-foreground">HCS records</div><div className="text-2xl font-semibold">{active.counts.hcs}</div></div>
                </div>
                {active.notes && (
                  <div className="rounded-lg border bg-background/60 p-3 text-sm text-muted-foreground">
                    {active.notes}
                  </div>
                )}
                <div className="space-y-2">
                  <div className="text-sm font-medium">Seed source files</div>
                  <div className="space-y-2">
                    {(active.source_manifest?.files || []).map((file) => (
                      <div key={file.path} className="flex flex-col items-start gap-2 rounded-lg border bg-background/60 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                        <span className="min-w-0 break-all font-mono text-xs sm:text-sm">{file.path}</span>
                        <span className="font-mono text-xs text-muted-foreground">{file.sha256.slice(0, 12)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="text-sm text-muted-foreground">No methodology version available yet.</div>
            )}
          </div>

          <div className="space-y-4 rounded-xl border bg-card/50 p-4">
            <div>
              <h2 className="font-semibold">Methodology history</h2>
              <p className="text-sm text-muted-foreground">Draft creation/activation is live here; deep content editing remains a later CR01 slice.</p>
            </div>
            {flatMethodologyVersions.map((version) => (
              <div key={version.version_id} className="space-y-3 rounded-lg border bg-background/60 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{version.methodology}</span>
                  <Badge variant="outline">v{version.version_no}</Badge>
                  <Badge variant={version.status === "active" ? "success" : "outline"}>{version.status}</Badge>
                  <Badge variant="outline">{version.source}</Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  {version.pillar_count} pillars · {version.lens_count} lenses · {version.hook_type_count} hooks · {version.hcs_count} HCS
                </div>
                {version.status === "draft" ? (
                  <div className="space-y-2">
                    <Textarea
                      value={methodologyNotes[version.version_id] || ""}
                      onChange={(e) => setMethodologyNotes((current) => ({ ...current, [version.version_id]: e.target.value }))}
                      className="min-h-[88px]"
                      placeholder="Draft notes for this methodology version"
                    />
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Button
                        variant="outline"
                        className="justify-center"
                        disabled={busy === `methodology:save:${version.version_id}`}
                        onClick={() => saveMethodologyDraft(version.version_id)}
                      >
                        <Save />{busy === `methodology:save:${version.version_id}` ? "Saving..." : "Save draft"}
                      </Button>
                      <Button
                        className="justify-center"
                        disabled={busy === `methodology:activate:${version.version_id}`}
                        onClick={() => activateMethodologyDraft(version.version_id)}
                      >
                        <Shield />{busy === `methodology:activate:${version.version_id}` ? "Activating..." : "Activate version"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{version.notes || "No version notes."}</div>
                )}
              </div>
            ))}
            {!flatMethodologyVersions.length && <div className="text-sm text-muted-foreground">No methodology history found.</div>}
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[0.8fr,1.2fr]">
          <div className="space-y-4 rounded-xl border bg-card/50 p-4">
            <div>
              <h2 className="font-semibold">Platforms</h2>
              <p className="text-sm text-muted-foreground">Registry foundation for publish targets and control channels.</p>
            </div>
            <div className="space-y-2">
              {(formatCatalog?.platforms || []).map((platform) => (
                <div key={platform.platform_id} className="rounded-lg border bg-background/60 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{platform.name}</span>
                    <Badge variant="outline">{platform.platform_key}</Badge>
                    <Badge variant="secondary">{platform.channel_role}</Badge>
                    {!platform.active && <Badge variant="outline">inactive</Badge>}
                  </div>
                  {platform.description && <div className="mt-2 text-sm text-muted-foreground">{platform.description}</div>}
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-4 rounded-xl border bg-card/50 p-4">
            <div>
              <h2 className="font-semibold">Content types</h2>
              <p className="text-sm text-muted-foreground">Managed registry for format definitions, platform targets, and downstream script/production guidance.</p>
            </div>

            {catalog?.can_administer && (
              <div className="space-y-3 rounded-lg border bg-background/60 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="font-medium">Create content type</div>
                    <div className="text-sm text-muted-foreground">New types start as draft definitions and affect runtime only after activation.</div>
                  </div>
                  <Button
                    variant="outline"
                    className="justify-center"
                    disabled={busy === "format:reset"}
                    onClick={resetFormatRegistry}
                  >
                    <RefreshCcw />{busy === "format:reset" ? "Resetting..." : "Reset registry"}
                  </Button>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Key</span>
                    <Input value={newFormat.format_key} onChange={(e) => setNewFormat((current) => ({ ...current, format_key: e.target.value }))} placeholder="hero_reel" />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Name</span>
                    <Input value={newFormat.name} onChange={(e) => setNewFormat((current) => ({ ...current, name: e.target.value }))} placeholder="Hero Reel" />
                  </label>
                </div>
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">Description</span>
                  <Textarea value={newFormat.description} onChange={(e) => setNewFormat((current) => ({ ...current, description: e.target.value }))} className="min-h-[72px]" />
                </label>
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">Use case</span>
                  <Textarea value={newFormat.use_case} onChange={(e) => setNewFormat((current) => ({ ...current, use_case: e.target.value }))} className="min-h-[72px]" />
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Lenses</span>
                    <Input value={newFormat.lens_fit} onChange={(e) => setNewFormat((current) => ({ ...current, lens_fit: e.target.value }))} placeholder="L1, L2, L3" />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span className="text-muted-foreground">Platform targets</span>
                    <Input value={newFormat.platform_targets} onChange={(e) => setNewFormat((current) => ({ ...current, platform_targets: e.target.value }))} placeholder="instagram, tiktok" />
                  </label>
                </div>
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">Production notes</span>
                  <Textarea value={newFormat.production_notes} onChange={(e) => setNewFormat((current) => ({ ...current, production_notes: e.target.value }))} className="min-h-[72px]" />
                </label>
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">Advanced spec JSON</span>
                  <Textarea value={newFormat.production_rules} onChange={(e) => setNewFormat((current) => ({ ...current, production_rules: e.target.value }))} className="min-h-[200px] font-mono text-xs" />
                </label>
                <Button className="justify-center" disabled={busy === "format:new"} onClick={createContentType}>
                  <Plus />{busy === "format:new" ? "Creating..." : "Create draft"}
                </Button>
              </div>
            )}
            <div className="space-y-3">
              {(formatCatalog?.formats || []).map((format) => {
                const draft = format.versions.find((version) => version.status === "draft") || null;
                const working = draft || format.active_version;
                const draftState = draft ? formatDrafts[draft.version_id] : null;
                const catalogState = formatCatalogDrafts[format.content_format_id];
                return (
                  <div key={format.content_format_id} className="space-y-3 rounded-lg border bg-background/60 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{format.name}</span>
                      <Badge variant="outline">{format.format_key}</Badge>
                      {format.lifecycle_status && <Badge variant={format.lifecycle_status === "archived" ? "outline" : "secondary"}>{format.lifecycle_status}</Badge>}
                      {working && <Badge variant={working.status === "draft" ? "warning" : "outline"}>v{working.version_no} · {working.status}</Badge>}
                      {catalog?.can_administer && !draft && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="ml-auto justify-center"
                          disabled={busy === `format:create:${format.format_key}`}
                          onClick={() => createFormatDraft(format.format_key)}
                        >
                          <GitBranch />{busy === `format:create:${format.format_key}` ? "Creating..." : "Clone to draft"}
                        </Button>
                      )}
                    </div>

                    {catalogState && (
                      <div className="grid gap-3 md:grid-cols-[1fr,1fr,auto]">
                        <label className="block space-y-1 text-sm">
                          <span className="text-muted-foreground">Key</span>
                          <Input
                            value={catalogState.format_key}
                            onChange={(e) => setFormatCatalogDrafts((current) => ({
                              ...current,
                              [format.content_format_id]: { ...catalogState, format_key: e.target.value },
                            }))}
                          />
                        </label>
                        <label className="block space-y-1 text-sm">
                          <span className="text-muted-foreground">Name</span>
                          <Input
                            value={catalogState.name}
                            onChange={(e) => setFormatCatalogDrafts((current) => ({
                              ...current,
                              [format.content_format_id]: { ...catalogState, name: e.target.value },
                            }))}
                          />
                        </label>
                        {catalog?.can_administer && (
                          <div className="flex items-end">
                            <Button
                              variant="outline"
                              className="w-full justify-center"
                              disabled={busy === `format:catalog:${format.content_format_id}`}
                              onClick={() => saveFormatCatalog(format.content_format_id)}
                            >
                              <Save />{busy === `format:catalog:${format.content_format_id}` ? "Saving..." : "Save type"}
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                    {catalogState && (
                      <label className="block space-y-1 text-sm">
                        <span className="text-muted-foreground">Description</span>
                        <Textarea
                          value={catalogState.description}
                          onChange={(e) => setFormatCatalogDrafts((current) => ({
                            ...current,
                            [format.content_format_id]: { ...catalogState, description: e.target.value },
                          }))}
                          className="min-h-[72px]"
                        />
                      </label>
                    )}

                    {working && !draft && (
                      <>
                        <div className="text-sm text-muted-foreground">{working.use_case || "No use case documented."}</div>
                        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                          <span>lenses: {working.lens_fit.join(", ") || "none"}</span>
                          <span>platforms: {working.platform_targets.join(", ") || "none"}</span>
                        </div>
                        {working.production_notes && <div className="text-sm text-muted-foreground">{working.production_notes}</div>}
                        <FrameworkPanel rules={working.production_rules} />
                        {catalog?.can_administer && (
                          <div className="flex flex-col gap-2 sm:flex-row">
                            {format.lifecycle_status === "archived" ? (
                              <Button
                                variant="outline"
                                className="justify-center"
                                disabled={busy === `format:restore:${format.content_format_id}`}
                                onClick={() => restoreFormat(format.content_format_id)}
                              >
                                <RotateCcw />{busy === `format:restore:${format.content_format_id}` ? "Restoring..." : "Restore"}
                              </Button>
                            ) : (
                              <Button
                                variant="outline"
                                className="justify-center"
                                disabled={busy === `format:archive:${format.content_format_id}`}
                                onClick={() => archiveFormat(format.content_format_id)}
                              >
                                <Archive />{busy === `format:archive:${format.content_format_id}` ? "Archiving..." : "Archive"}
                              </Button>
                            )}
                            <Button
                              variant="outline"
                              className="justify-center text-destructive"
                              disabled={busy === `format:delete:${format.content_format_id}`}
                              onClick={() => deleteFormat(format.content_format_id, format.name)}
                            >
                              <Trash2 />{busy === `format:delete:${format.content_format_id}` ? "Deleting..." : "Delete"}
                            </Button>
                          </div>
                        )}
                      </>
                    )}

                    {draft && draftState && (
                      <div className="space-y-3">
                        <FrameworkPanel rules={draft.production_rules} />
                        <label className="block space-y-1 text-sm">
                          <span className="text-muted-foreground">Use case</span>
                          <Textarea
                            value={draftState.use_case}
                            onChange={(e) => setFormatDrafts((current) => ({
                              ...current,
                              [draft.version_id]: { ...draftState, use_case: e.target.value },
                            }))}
                            className="min-h-[76px]"
                          />
                        </label>
                        <div className="grid gap-3 md:grid-cols-2">
                          <label className="block space-y-1 text-sm">
                            <span className="text-muted-foreground">Lenses</span>
                            <Input
                              value={draftState.lens_fit}
                              onChange={(e) => setFormatDrafts((current) => ({
                                ...current,
                                [draft.version_id]: { ...draftState, lens_fit: e.target.value },
                              }))}
                              placeholder="L1, L2, L3"
                            />
                          </label>
                          <label className="block space-y-1 text-sm">
                            <span className="text-muted-foreground">Platform targets</span>
                            <Input
                              value={draftState.platform_targets}
                              onChange={(e) => setFormatDrafts((current) => ({
                                ...current,
                                [draft.version_id]: { ...draftState, platform_targets: e.target.value },
                              }))}
                              placeholder="instagram, telegram"
                            />
                          </label>
                        </div>
                        <label className="block space-y-1 text-sm">
                          <span className="text-muted-foreground">Production notes</span>
                          <Textarea
                            value={draftState.production_notes}
                            onChange={(e) => setFormatDrafts((current) => ({
                              ...current,
                              [draft.version_id]: { ...draftState, production_notes: e.target.value },
                            }))}
                            className="min-h-[96px]"
                          />
                        </label>
                        <label className="block space-y-1 text-sm">
                          <span className="text-muted-foreground">Advanced spec JSON</span>
                          <Textarea
                            value={draftState.production_rules}
                            onChange={(e) => setFormatDrafts((current) => ({
                              ...current,
                              [draft.version_id]: { ...draftState, production_rules: e.target.value },
                            }))}
                            className="min-h-[220px] font-mono text-xs"
                          />
                        </label>
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <Button
                            variant="outline"
                            className="justify-center"
                            disabled={busy === `format:save:${draft.version_id}`}
                            onClick={() => saveFormatDraft(draft.version_id)}
                          >
                            <Save />{busy === `format:save:${draft.version_id}` ? "Saving..." : "Save draft"}
                          </Button>
                          <Button
                            className="justify-center"
                            disabled={busy === `format:activate:${draft.version_id}`}
                            onClick={() => activateFormatDraft(draft.version_id)}
                          >
                            <Shield />{busy === `format:activate:${draft.version_id}` ? "Activating..." : "Activate version"}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
