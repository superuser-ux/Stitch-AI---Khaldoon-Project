"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowUp, ArrowDown, Check, GitBranch, Plus, RotateCcw, Save, Shield, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { stageLabel } from "@/lib/stages";

type Principal = { principal_id: string; display_name_en: string | null };
type PrincipalRole = { role_id: string; display_name_en: string | null; members: number };
type PrincipalGroup = { group_id: string; display_name_en: string | null; members: number };
type ApprovalAssignment = { assignment_kind: string; assignment_key: string; display_name_en?: string | null };
type ApprovalPolicy = {
  stage: string; rule_key: string; users: string[]; roles: string[]; groups: string[];
  assignments: ApprovalAssignment[]; source?: "db" | "yaml"; updated_by?: string;
};
type WorkflowTransition = {
  transition_id?: string; from_stage_key: string; to_stage_key: string; condition_key: string; enabled: boolean;
};
type WorkflowStage = {
  stage_id?: string; stage_key: string; stage_label: string; stage_group: string; ordinal: number;
  enabled: boolean; bypassable: boolean; mandatory: boolean; gate_stage: string; stage_kind: string;
  generator_kind?: string | null; scope?: string | null; policy?: string | null; review_statuses: string[];
  approve_to?: string | null; changes_to?: string | null; reject_to?: string | null; rework_mode?: string | null;
  generates_from?: string | null; writer_mode?: string | null; requires_flag?: string | null;
  allow_partial_batch: boolean; enforce_mandatory_reviews: boolean; approval_rule: string;
};
type WorkflowVersion = {
  workflow_id: string; workflow_key: string; name: string; description: string | null;
  version_id: string; version_no: number; status: string; source: string; notes: string | null;
  created_by?: string | null; updated_by?: string | null; activated_by?: string | null;
  stages: WorkflowStage[]; transitions: WorkflowTransition[];
};
type WorkflowSummary = {
  workflow_id: string; workflow_key: string; name: string; description: string | null;
  active_version_id: string | null;
  versions: {
    version_id: string; version_no: number; status: string; source: string; notes?: string | null;
    created_by?: string | null; activated_by?: string | null;
  }[];
};
type WorkflowCatalog = {
  can_administer: boolean;
  workflows: WorkflowSummary[];
  active_version: WorkflowVersion | null;
};
type PolicyDraft = { rule_key: string; users: string[]; roles: string[]; groups: string[] };

const GW = "/gw";
// #39 — labels sourced from the single stage-identity model (keyed by canonical gate id); this admin
// picker keeps using the canonical gate id as `key`, only the display label is de-duplicated here.
const STAGE_LIBRARY = [
  { key: "topic_review", group: "Content" },
  { key: "script_review", group: "Content" },
  { key: "native_review", group: "Sign-off" },
  { key: "scholar_review", group: "Sign-off" },
  { key: "final_review", group: "Sign-off" },
  { key: "production_review", group: "Production" },
  { key: "edit_review", group: "Production" },
  { key: "distribution_review", group: "Production" },
].map((s) => ({ ...s, label: stageLabel(s.key) }));

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

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

function toggleValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

function emptyPolicyDraft() {
  return { rule_key: "any", users: [], roles: [], groups: [] };
}

function approvalAssignmentLabel(a: ApprovalAssignment) {
  return `${a.assignment_kind}:${a.display_name_en || a.assignment_key}`;
}

export function WorkflowAdmin() {
  const [reviewer, setReviewer] = useState<string>("khal");
  const [catalog, setCatalog] = useState<WorkflowCatalog | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string>("");
  const [version, setVersion] = useState<WorkflowVersion | null>(null);
  const [draft, setDraft] = useState<WorkflowVersion | null>(null);
  const [approvers, setApprovers] = useState<Principal[]>([]);
  const [roles, setRoles] = useState<PrincipalRole[]>([]);
  const [groups, setGroups] = useState<PrincipalGroup[]>([]);
  const [approvalPolicies, setApprovalPolicies] = useState<Record<string, ApprovalPolicy>>({});
  const [policyDrafts, setPolicyDrafts] = useState<Record<string, PolicyDraft>>({});
  const [editingPolicyStage, setEditingPolicyStage] = useState<string | null>(null);
  const [newStageKey, setNewStageKey] = useState<string>("");
  const [busy, setBusy] = useState<string>("");
  const [message, setMessage] = useState<string>("");
  const [error, setError] = useState<string>("");

  const canAdmin = !!catalog?.can_administer;

  const loadCatalog = async () => {
    const [catalogRes, approverRes, rolesRes, groupsRes, policiesRes] = await Promise.all([
      jget<WorkflowCatalog>("/workflows"),
      jget<Principal[]>("/principals?kind=user&active=true&module=content"),
      jget<PrincipalRole[]>("/principal-roles?active=true&module=content"),
      jget<PrincipalGroup[]>("/principal-groups?active=true&module=content"),
      jget<{ can_administer: boolean; policies: ApprovalPolicy[] }>("/approval-policies"),
    ]);
    setCatalog(catalogRes);
    setApprovers(approverRes);
    setRoles(rolesRes);
    setGroups(groupsRes);
    setApprovalPolicies(Object.fromEntries(policiesRes.policies.map((p) => [p.stage, p])));
    const firstVersion = selectedVersionId
      || catalogRes.active_version?.version_id
      || catalogRes.workflows[0]?.versions[0]?.version_id
      || "";
    if (firstVersion) setSelectedVersionId(firstVersion);
  };

  useEffect(() => {
    loadCatalog().catch((e) => setError(String(e)));
    jget<{ reviewer: string }>("/api/reviewer")
      .then((r) => setReviewer(r.reviewer))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedVersionId) return;
    jget<WorkflowVersion>(`/workflow-versions/${selectedVersionId}`)
      .then((res) => {
        setVersion(res);
        setDraft(clone(res));
      })
      .catch((e) => setError(String(e)));
  }, [selectedVersionId]);

  const availableStageOptions = useMemo(() => {
    const used = new Set((draft?.stages || []).map((s) => s.stage_key));
    return STAGE_LIBRARY.filter((s) => !used.has(s.key));
  }, [draft]);

  const resetDraft = () => {
    if (!version) return;
    setDraft(clone(version));
    setError("");
    setMessage("Draft reset to the last saved version.");
  };

  const updateStage = (stageKey: string, patch: Partial<WorkflowStage>) => {
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        stages: current.stages.map((stage) => stage.stage_key === stageKey ? { ...stage, ...patch } : stage),
      };
    });
  };

  const reorderStages = (stageKey: string, delta: number) => {
    setDraft((current) => {
      if (!current) return current;
      const idx = current.stages.findIndex((stage) => stage.stage_key === stageKey);
      const next = idx + delta;
      if (idx < 0 || next < 0 || next >= current.stages.length) return current;
      const stages = [...current.stages];
      const [row] = stages.splice(idx, 1);
      stages.splice(next, 0, row);
      return {
        ...current,
        stages: stages.map((stage, ordinal) => ({ ...stage, ordinal: ordinal + 1 })),
      };
    });
  };

  const removeStage = (stageKey: string) => {
    setDraft((current) => {
      if (!current) return current;
      const stages = current.stages.filter((stage) => stage.stage_key !== stageKey)
        .map((stage, ordinal) => ({ ...stage, ordinal: ordinal + 1 }));
      const transitions = current.transitions.filter((t) => t.from_stage_key !== stageKey && t.to_stage_key !== stageKey);
      return { ...current, stages, transitions };
    });
  };

  const addStage = () => {
    if (!newStageKey) return;
    const meta = STAGE_LIBRARY.find((stage) => stage.key === newStageKey);
    if (!meta) return;
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        stages: [...current.stages, {
          stage_key: meta.key,
          stage_label: meta.label,
          stage_group: meta.group,
          ordinal: current.stages.length + 1,
          enabled: true,
          bypassable: false,
          mandatory: true,
          gate_stage: meta.key,
          stage_kind: "transition",
          generator_kind: null,
          scope: null,
          policy: null,
          review_statuses: [],
          approve_to: null,
          changes_to: null,
          reject_to: null,
          rework_mode: null,
          generates_from: null,
          writer_mode: null,
          requires_flag: null,
          allow_partial_batch: false,
          enforce_mandatory_reviews: false,
          approval_rule: "any",
        }],
      };
    });
    setNewStageKey("");
  };

  const addTransition = () => {
    setDraft((current) => {
      if (!current || current.stages.length < 2) return current;
      return {
        ...current,
        transitions: [...current.transitions, {
          from_stage_key: current.stages[0].stage_key,
          to_stage_key: current.stages[1].stage_key,
          condition_key: "approve",
          enabled: true,
        }],
      };
    });
  };

  const updateTransition = (idx: number, patch: Partial<WorkflowTransition>) => {
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        transitions: current.transitions.map((transition, index) => index === idx ? { ...transition, ...patch } : transition),
      };
    });
  };

  const removeTransition = (idx: number) => {
    setDraft((current) => current ? { ...current, transitions: current.transitions.filter((_, index) => index !== idx) } : current);
  };

  const createDraft = async () => {
    if (!catalog?.workflows[0]) return;
    setBusy("create-draft");
    setError("");
    try {
      const created = await jpost<WorkflowVersion>(`/workflows/${catalog.workflows[0].workflow_key}/versions/draft`, {});
      setVersion(created);
      setDraft(clone(created));
      setSelectedVersionId(created.version_id);
      await loadCatalog();
      setMessage(`Created draft v${created.version_no}.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  const saveDraft = async () => {
    if (!draft) return;
    setBusy("save-draft");
    setError("");
    try {
      const saved = await jput<WorkflowVersion>(`/workflow-versions/${draft.version_id}`, {
        notes: draft.notes,
        stages: draft.stages,
        transitions: draft.transitions,
      });
      setVersion(saved);
      setDraft(clone(saved));
      await loadCatalog();
      setMessage(`Saved workflow draft v${saved.version_no}.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  const activateDraft = async () => {
    if (!draft) return;
    setBusy("activate-draft");
    setError("");
    try {
      const activated = await jpost<WorkflowVersion>(`/workflow-versions/${draft.version_id}/activate`, {});
      setVersion(activated);
      setDraft(clone(activated));
      await loadCatalog();
      setMessage(`Activated workflow v${activated.version_no}.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  const beginPolicyEdit = (stage: string) => {
    const policy = approvalPolicies[stage];
    setEditingPolicyStage(stage);
    setPolicyDrafts((current) => ({
      ...current,
      [stage]: policy
        ? { rule_key: policy.rule_key, users: [...policy.users], roles: [...policy.roles], groups: [...policy.groups] }
        : emptyPolicyDraft(),
    }));
  };

  const savePolicy = async (stage: string) => {
    const draftPolicy = policyDrafts[stage];
    if (!draftPolicy) return;
    setBusy(`policy:${stage}`);
    setError("");
    try {
      const saved = await jput<ApprovalPolicy>(`/stages/${stage}/approval-policy`, {
        rule: draftPolicy.rule_key,
        users: draftPolicy.users,
        roles: draftPolicy.roles,
        groups: draftPolicy.groups,
      });
      setApprovalPolicies((current) => ({ ...current, [stage]: saved }));
      setEditingPolicyStage(null);
      setMessage(`Updated approval policy for ${stage}.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Badge variant="outline">Admin</Badge>
              <Badge variant="outline">{reviewer}</Badge>
              {canAdmin ? <Badge className="bg-success text-white hover:bg-success">can administer</Badge> : <Badge variant="outline">read only</Badge>}
            </div>
            <h1 className="text-2xl font-semibold">Workflow Admin</h1>
            <p className="text-sm text-muted-foreground">Versioned workflow control plane and approval assignment editor.</p>
          </div>
          <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:flex-row sm:items-center">
            <Button asChild variant="outline" className="justify-center"><Link href="/"><ArrowLeft />Back to operations</Link></Button>
            <Button asChild variant="outline" className="justify-center"><Link href="/admin/methodology"><GitBranch />Methodology admin</Link></Button>
            {canAdmin && <Button onClick={createDraft} disabled={busy === "create-draft"} className="justify-center"><GitBranch />{busy === "create-draft" ? "Creating..." : "Clone active to draft"}</Button>}
          </div>
        </div>

        {(message || error) && (
          <div className={`rounded-lg border px-4 py-3 text-sm ${error ? "border-destructive/40 text-destructive" : "border-success/40 text-success"}`}>
            {error || message}
          </div>
        )}

        <section className="grid min-w-0 gap-4 xl:grid-cols-[320px,1fr]">
          <div className="min-w-0 space-y-4 rounded-xl border bg-card/50 p-4">
            <div>
              <h2 className="font-semibold">Workflows</h2>
              <p className="text-sm text-muted-foreground">One active workflow at a time for this content space.</p>
            </div>
            {catalog?.workflows.map((workflow) => (
              <div key={workflow.workflow_id} className="space-y-3 rounded-lg border bg-background/60 p-3">
                <div>
                  <div className="font-medium">{workflow.name}</div>
                  <div className="text-xs text-muted-foreground">{workflow.workflow_key}</div>
                </div>
                <div className="space-y-2">
                  {workflow.versions.map((item) => (
                    <button
                      key={item.version_id}
                      onClick={() => setSelectedVersionId(item.version_id)}
                      className={`flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm ${selectedVersionId === item.version_id ? "border-primary bg-primary/5" : "border-border bg-background/70"}`}
                    >
                      <span className="font-medium">v{item.version_no}</span>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{item.status}</Badge>
                        {workflow.active_version_id === item.version_id && <Check className="size-4 text-success" />}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="min-w-0 space-y-4 rounded-xl border bg-card/50 p-4">
            {!draft ? (
              <div className="py-12 text-center text-sm text-muted-foreground">Select a workflow version to inspect it.</div>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-semibold">{draft.name}</h2>
                      <Badge variant="outline">v{draft.version_no}</Badge>
                      <Badge variant="outline">{draft.status}</Badge>
                      <Badge variant="outline">{draft.source}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{draft.description || "No description."}</p>
                  </div>
                  {canAdmin && draft.status === "draft" && (
                    <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:flex-row sm:items-center">
                      <Button variant="outline" onClick={resetDraft} className="justify-center"><RotateCcw />Reset</Button>
                      <Button variant="outline" onClick={saveDraft} disabled={busy === "save-draft"} className="justify-center"><Save />{busy === "save-draft" ? "Saving..." : "Save draft"}</Button>
                      <Button onClick={activateDraft} disabled={busy === "activate-draft"} className="justify-center"><Shield />{busy === "activate-draft" ? "Activating..." : "Activate version"}</Button>
                    </div>
                  )}
                </div>

                <div className="space-y-2">
                  <label className="block text-sm font-medium">Release notes</label>
                  <Textarea
                    value={draft.notes || ""}
                    onChange={(e) => setDraft((current) => current ? { ...current, notes: e.target.value } : current)}
                    disabled={!canAdmin || draft.status !== "draft"}
                    className="min-h-[96px]"
                  />
                </div>

                <section className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="font-semibold">Stages</h3>
                      <p className="text-sm text-muted-foreground">Supported stage catalog only, kept compatible with the live engine.</p>
                    </div>
                    {canAdmin && draft.status === "draft" && (
                      <div className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:flex-row sm:items-center">
                        <Select value={newStageKey} onValueChange={setNewStageKey}>
                          <SelectTrigger className="w-full sm:w-[220px]"><SelectValue placeholder="Add a stage" /></SelectTrigger>
                          <SelectContent>
                            {availableStageOptions.map((option) => (
                              <SelectItem key={option.key} value={option.key}>{option.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button variant="outline" onClick={addStage} disabled={!newStageKey} className="justify-center"><Plus />Add</Button>
                      </div>
                    )}
                  </div>

                  <div className="space-y-3">
                    {draft.stages.map((stage, idx) => (
                      <div key={stage.stage_key} className="space-y-3 rounded-lg border bg-background/70 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <Badge variant="outline">{idx + 1}</Badge>
                              <div className="break-all font-medium">{stage.stage_key}</div>
                              <Badge variant="outline">{stage.stage_group}</Badge>
                              <Badge variant="outline">{stage.stage_kind}</Badge>
                            </div>
                            <div className="break-all text-sm text-muted-foreground">{stage.gate_stage}</div>
                          </div>
                          {canAdmin && draft.status === "draft" && (
                            <div className="flex items-center gap-2">
                              <Button variant="outline" size="sm" onClick={() => reorderStages(stage.stage_key, -1)} disabled={idx === 0}><ArrowUp /></Button>
                              <Button variant="outline" size="sm" onClick={() => reorderStages(stage.stage_key, 1)} disabled={idx === draft.stages.length - 1}><ArrowDown /></Button>
                              <Button variant="outline" size="sm" onClick={() => removeStage(stage.stage_key)}><Trash2 /></Button>
                            </div>
                          )}
                        </div>

                        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                          <label className="space-y-1 text-sm">
                            <span className="text-muted-foreground">Label</span>
                            <Input value={stage.stage_label} disabled={!canAdmin || draft.status !== "draft"} onChange={(e) => updateStage(stage.stage_key, { stage_label: e.target.value })} />
                          </label>
                          <label className="space-y-1 text-sm">
                            <span className="text-muted-foreground">Group</span>
                            <Input value={stage.stage_group} disabled={!canAdmin || draft.status !== "draft"} onChange={(e) => updateStage(stage.stage_key, { stage_group: e.target.value })} />
                          </label>
                          <label className="space-y-1 text-sm">
                            <span className="text-muted-foreground">Approval rule</span>
                            <Select value={stage.approval_rule} onValueChange={(value) => updateStage(stage.stage_key, { approval_rule: value })} disabled={!canAdmin || draft.status !== "draft"}>
                              <SelectTrigger><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="any">OR</SelectItem>
                                <SelectItem value="all">AND</SelectItem>
                              </SelectContent>
                            </Select>
                          </label>
                          <label className="space-y-1 text-sm">
                            <span className="text-muted-foreground">Generator</span>
                            <Input value={stage.generator_kind || ""} disabled={!canAdmin || draft.status !== "draft"} onChange={(e) => updateStage(stage.stage_key, { generator_kind: e.target.value || null })} />
                          </label>
                        </div>

                        <div className="flex flex-wrap gap-4 text-sm">
                          {([
                            ["enabled", stage.enabled],
                            ["bypassable", stage.bypassable],
                            ["mandatory", stage.mandatory],
                            ["allow partial batch", stage.allow_partial_batch],
                            ["enforce mandatory reviews", stage.enforce_mandatory_reviews],
                          ] as const).map(([label, checked]) => (
                            <label key={label} className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                checked={checked}
                                disabled={!canAdmin || draft.status !== "draft"}
                                onChange={(e) => updateStage(stage.stage_key, {
                                  [label === "allow partial batch" ? "allow_partial_batch"
                                    : label === "enforce mandatory reviews" ? "enforce_mandatory_reviews"
                                      : label]: e.target.checked,
                                } as Partial<WorkflowStage>)}
                              />
                              <span>{label}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="font-semibold">Transitions</h3>
                      <p className="text-sm text-muted-foreground">Explicit stage-to-stage transitions for the active workflow version.</p>
                    </div>
                    {canAdmin && draft.status === "draft" && <Button variant="outline" onClick={addTransition}><Plus />Add transition</Button>}
                  </div>

                  <div className="space-y-3">
                    {draft.transitions.map((transition, idx) => (
                      <div key={`${transition.from_stage_key}-${transition.to_stage_key}-${idx}`} className="grid gap-3 rounded-lg border bg-background/70 p-4 md:grid-cols-[1fr,1fr,180px,120px,auto]">
                        <Select value={transition.from_stage_key} onValueChange={(value) => updateTransition(idx, { from_stage_key: value })} disabled={!canAdmin || draft.status !== "draft"}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {draft.stages.map((stage) => <SelectItem key={stage.stage_key} value={stage.stage_key}>{stage.stage_label}</SelectItem>)}
                          </SelectContent>
                        </Select>
                        <Select value={transition.to_stage_key} onValueChange={(value) => updateTransition(idx, { to_stage_key: value })} disabled={!canAdmin || draft.status !== "draft"}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {draft.stages.map((stage) => <SelectItem key={stage.stage_key} value={stage.stage_key}>{stage.stage_label}</SelectItem>)}
                          </SelectContent>
                        </Select>
                        <Input value={transition.condition_key} disabled={!canAdmin || draft.status !== "draft"} onChange={(e) => updateTransition(idx, { condition_key: e.target.value })} />
                        <label className="flex items-center gap-2 text-sm">
                          <input type="checkbox" checked={transition.enabled} disabled={!canAdmin || draft.status !== "draft"} onChange={(e) => updateTransition(idx, { enabled: e.target.checked })} />
                          enabled
                        </label>
                        {canAdmin && draft.status === "draft" && <Button variant="outline" onClick={() => removeTransition(idx)}><Trash2 /></Button>}
                      </div>
                    ))}
                  </div>
                </section>
              </>
            )}
          </div>
        </section>

        <section className="min-w-0 space-y-4 rounded-xl border bg-card/50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold">Approval Assignment Policies</h2>
              <p className="text-sm text-muted-foreground">Named users, roles, and groups with OR/AND rules, managed outside the operational workflow surface.</p>
            </div>
            <Badge variant="outline">{Object.keys(approvalPolicies).length} stages</Badge>
          </div>

          <div className="grid min-w-0 gap-4 xl:grid-cols-2">
            {STAGE_LIBRARY.map((entry) => {
              const policy = approvalPolicies[entry.key];
              const draftPolicy = policyDrafts[entry.key] || emptyPolicyDraft();
              const editing = editingPolicyStage === entry.key;
              const selectionCount = draftPolicy.users.length + draftPolicy.roles.length + draftPolicy.groups.length;
              return (
                <div key={entry.key} className="min-w-0 space-y-3 rounded-lg border bg-background/70 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{entry.label}</div>
                      <div className="text-xs text-muted-foreground">{entry.key}</div>
                    </div>
                    {canAdmin && (
                      <div className="flex items-center gap-2">
                        {editing ? (
                          <>
                            <Button variant="outline" size="sm" onClick={() => setEditingPolicyStage(null)}>Cancel</Button>
                            <Button size="sm" disabled={!selectionCount || busy === `policy:${entry.key}`} onClick={() => savePolicy(entry.key)}>
                              {busy === `policy:${entry.key}` ? "Saving..." : "Save"}
                            </Button>
                          </>
                        ) : (
                          <Button variant="outline" size="sm" onClick={() => beginPolicyEdit(entry.key)}>Edit</Button>
                        )}
                      </div>
                    )}
                  </div>

                  {editing ? (
                    <div className="space-y-3">
                      <label className="block space-y-1 text-sm">
                        <span className="text-muted-foreground">Rule</span>
                        <Select value={draftPolicy.rule_key} onValueChange={(value) => setPolicyDrafts((current) => ({ ...current, [entry.key]: { ...draftPolicy, rule_key: value } }))}>
                          <SelectTrigger className="w-[120px]"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="any">OR</SelectItem>
                            <SelectItem value="all">AND</SelectItem>
                          </SelectContent>
                        </Select>
                      </label>

                      <div className="space-y-2">
                        <div className="text-sm text-muted-foreground">Named users</div>
                        <div className="flex flex-wrap gap-2">
                          {approvers.map((user) => {
                            const active = draftPolicy.users.includes(user.principal_id);
                            return (
                              <Button key={user.principal_id} variant={active ? "default" : "outline"} size="sm"
                                onClick={() => setPolicyDrafts((current) => ({ ...current, [entry.key]: { ...draftPolicy, users: toggleValue(draftPolicy.users, user.principal_id) } }))}>
                                {user.display_name_en || user.principal_id}
                              </Button>
                            );
                          })}
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm text-muted-foreground">Roles</div>
                        <div className="flex flex-wrap gap-2">
                          {roles.map((role) => {
                            const active = draftPolicy.roles.includes(role.role_id);
                            return (
                              <Button key={role.role_id} variant={active ? "default" : "outline"} size="sm"
                                onClick={() => setPolicyDrafts((current) => ({ ...current, [entry.key]: { ...draftPolicy, roles: toggleValue(draftPolicy.roles, role.role_id) } }))}>
                                {role.display_name_en || role.role_id}
                              </Button>
                            );
                          })}
                        </div>
                      </div>

                      <div className="space-y-2">
                        <div className="text-sm text-muted-foreground">Groups</div>
                        <div className="flex flex-wrap gap-2">
                          {groups.length
                            ? groups.map((group) => {
                              const active = draftPolicy.groups.includes(group.group_id);
                              return (
                                <Button key={group.group_id} variant={active ? "default" : "outline"} size="sm"
                                  onClick={() => setPolicyDrafts((current) => ({ ...current, [entry.key]: { ...draftPolicy, groups: toggleValue(draftPolicy.groups, group.group_id) } }))}>
                                  {group.display_name_en || group.group_id}
                                </Button>
                              );
                            })
                            : <span className="text-sm text-muted-foreground">No groups configured.</span>}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{policy?.rule_key === "all" ? "AND" : "OR"}</Badge>
                        <Badge variant="outline">{policy?.source || "yaml"}</Badge>
                        {policy?.updated_by && <Badge variant="outline">updated by {policy.updated_by}</Badge>}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {(policy?.assignments || []).map((assignment) => (
                          <Badge key={`${assignment.assignment_kind}:${assignment.assignment_key}`} variant="outline">
                            {approvalAssignmentLabel(assignment)}
                          </Badge>
                        ))}
                        {!policy?.assignments.length && <span className="text-sm text-muted-foreground">No approval assignments configured.</span>}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
