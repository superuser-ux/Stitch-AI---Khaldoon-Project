"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { coerceViewForStage } from "./views";
import { stageLabel } from "./stages";
import { getSessionPersona, setSessionPersona, PERSONA_HEADER } from "./persona-session";
import { fetchRuntime } from "./client-trial";

// ---- types -----------------------------------------------------------------
export type Decision = { approver_id: string; decision: string; notes?: string | null };
export type Principal = {
  principal_id: string; kind: string; display_name_ar: string | null; display_name_en: string | null;
  role: string | null; roles: string[]; groups: string[];
};
export type PrincipalRole = {
  role_id: string; display_name_ar: string | null; display_name_en: string | null; members: number;
};
export type PrincipalGroup = {
  group_id: string; display_name_ar: string | null; display_name_en: string | null; members: number;
};
export type PendingApproval = {
  gate_id: string; stage: string; rule_key: string; status: string; round_id: string | null;
  total_targets: number; decided_targets: number; remaining_targets: number;
  matched_assignments: ApprovalAssignment[];
  all_assignments: ApprovalAssignment[];
};
export type ApprovalAssignment = {
  assignment_kind: string; assignment_key: string; resolved_principal_id?: string | null; display_name_en?: string | null;
};
export type GateAssignment = ApprovalAssignment & { resolved_principal_id: string | null; display_name_en: string };
export type Asset = { asset_id: string; stage: string; kind: string; uri: string | null;
  version: number; platform_variant: string | null; status: string };
export type Directive = { type: string; to_stage: string; revision: number;
  payload: { intent?: { ar?: string; en?: string }; acceptance_criteria?: string[] } };
export type ScriptStructure = Record<string, string>;
// #93/#50 — the actual selected framework for a content format (from the managed content-format
// registry, GET /content-formats → active_version.production_rules), keyed by format NAME so a topic
// card (which carries `format`) can surface the real framework name + component step labels.
// #149 (#146 S2) — structureOrder/structureLabels carry the format's registry-driven script
// structure (production_rules.structure step→label, in order) so the review card labels script
// beats from the SAME canonical source as the framework block — not a fixed UI dict.
export type Framework = {
  name: string; frameworkName: string | null; summary: string | null; components: string[];
  structureOrder: string[]; structureLabels: Record<string, string>;
  // #177 — registry truth marker: "managed" (client framework seeded), "legacy_carry_forward"
  // (client never provided one), or null (unmarked/no registry data). Lets the UI disclose
  // fallback/legacy states instead of presenting generic labels as client framework.
  frameworkStatus: string | null;
};
export type DeliveryCheck = Record<string, boolean>;
// #179 — one row of the durable "approved & moved forward" trail (server-derived, read-only)
export type AdvancedItem = {
  slot_id: string; round_id: string; status: string; pillar_code: string; hook_text: string | null;
  format: string | null; day: number; time_uae: string; topic_text: string | null;
  approved_at: string; approved_by: string;
  location_kind: "in_review" | "advanced" | "changes" | "dropped" | "other";
  location_stage: string | null; location_stage_label: string | null;
  // #219 — canonical ID fields (additive, read-only) so the completed-trail inspection controls
  // reuse the same content-ID formatter + Detailed descriptor as active review cards.
  pillar_short_code: string | null; seq_in_pillar: number | null;
  pillar_name_en: string | null; hcs_name_en: string | null;
};
// #237 Slice A — the status-independent read-only inspection projection for a completed-trail
// item: the same content definition the active card shows, from persisted truth only. Artifacts
// carry the slot_approval-pinned revision (else the head, labeled); null artifact = truthful absence.
export type InspectArtifact = {
  revision: number; approved: boolean; approved_by: string | null; approved_at: string | null;
  head_revision: number | null; feedback: string | null; change_summary_ar: string | null;
  change_summary_en: string | null; base_revision: number | null; created_at: string;
};
export type InspectTopic = InspectArtifact & {
  hook_text: string | null; text_ar: string | null;
  rationale_ar: string | null; rationale_en: string | null;
};
export type InspectScript = InspectArtifact & {
  script_ar: string | null; structure: ScriptStructure | null; final_line: string | null;
  delivery_notes: string | null; delivery_check: DeliveryCheck | null; flags: string[] | null;
  model: string | null; needs_scholar_review: boolean; needs_native_review: boolean;
};
export type InspectDecision = {
  stage: string; approver_id: string; decision: string; notes: string | null; decided_at: string;
};
// #255 S1 — the approved MASTER edit pin vs the current master head (exact master predicate:
// stage media_edit · kind edit · no platform variant). drifted = a newer master exists but the
// approved pin (and its display) must never move with it.
export type ApprovedEdit = {
  pinned_revision: number; pinned_asset_id: string | null;
  pin_evidence: "audit" | "unavailable" | "inconsistent";
  approved_by: string | null; approved_at: string | null;
  current_master_revision: number | null; current_master_ambiguous: boolean; drifted: boolean;
};
export type SlotInspect = {
  slot_id: string; round_id: string; status: string; day: number; time_uae: string;
  format: string | null; hook_text: string | null; hook_type: string | null;
  topic_angle: string | null; cycle_no: number | null;
  pillar_code: string; pillar_short_code: string | null;
  pillar_name_en: string | null; pillar_name_ar: string | null;
  hcs_id: string; seq_in_pillar: number | null; hcs_name_en: string | null; hcs_name_ar: string | null;
  lens: string | null; lens_name_en: string | null; lens_name_ar: string | null;
  location_kind: AdvancedItem["location_kind"];
  location_stage: string | null; location_stage_label: string | null;
  topic: InspectTopic | null; script: InspectScript | null;
  decisions: InspectDecision[]; assets: Asset[]; publications: PublicationRecord[];
  approved_edit: ApprovedEdit | null;
};
// #250 — slot-keyed read-only SDAM readiness visibility (Production/Edit surfaces). Bindings +
// newest PERSISTED observation state only; effective_state null = bound with no evidence yet
// (distinct from an observed provider 'pending'). handoff = the existing #244 build_handoff
// authorization; configured:false = this runtime truthfully has no live SDAM read path.
export type SdamBinding = {
  binding_id: string; asset_id: string; asset_version: number; provider_key: string;
  external_ref: string; mapping_version: number; created_at: string;
  effective_state: string | null; observed_result: string | null;
  observed_at: string | null; expires_at: string | null; handoff_ready: boolean;
  // #259 P1b — server-observable, reload-stable: registered but the field-100 discovery projection
  // is not yet confirmed. The bound card offers a governed projection-only retry for this state.
  projection_pending: boolean;
};
export type SlotSdam = { slot_id: string; bindings: SdamBinding[] };
export type SdamHandoff = {
  binding_id: string; configured: boolean; reason: string | null;
  handoff: {
    binding_id: string; asset_id: string; asset_version: number; mapping_version: number;
    externalRef: { system: string; id: string }; media_source: string;
  } | null;
};
// #200 (pub.v1) — a publication record: the governed intent plus (once attested) the durable
// occurrence, with its derived state and append-only event history. Server-derived, read-only here.
export type PublicationEvent = {
  event_seq: number; event_type: string; event_source: string; actor: string; created_at: string;
};
export type PublicationRecord = {
  publication_intent_id: string; publication_occurrence_id: string | null; slot_id: string;
  platform_key: string; destination: string | null; url: string | null;
  current_state: string; created_by: string; attested_by: string | null;
  created_at: string; recorded_at: string | null; events: PublicationEvent[];
};
export type PlatformOption = { platform_key: string; name: string | null };
// #271 — a planned calendar cell from the run read model (GET /rounds/{id} → round_detail). Sourced
// independently of the active gate so the calendar keeps EVERY positional cell after Schedule approval
// (continuity), showing each slot's lifecycle status — not just the current review subset.
export type RoundSlot = {
  slot_id: string; day: number; time_uae: string; pillar_code: string; pillar_short_code: string | null;
  format: string; hcs_id: string; seq_in_pillar: number | null; lens: string;
  hook_type: string | null; topic_angle: string | null; status: string;
};

export type Target = {
  // #292 — the round's accepted server display code, injected by the provider. null/absent = a
  // legacy round with no mapping generation, where the client derivation stays authoritative.
  display_code?: string | null;
  slot_id: string; day: number; time_uae: string; pillar_code: string; pillar_short_code: string;
  pillar_name_en: string; pillar_name_ar: string | null; hcs_id: string; seq_in_pillar: number;
  hcs_name_en: string; hcs_name_ar: string | null; lens: string; lens_name_en?: string | null; lens_name_ar?: string | null; format: string;
  hook_text: string | null; hook_type: string | null; topic_angle: string | null; slot_status: string;
  rationale_ar: string | null; rationale_en: string | null; topic_revision: number | null;
  topic_feedback: string | null; change_summary_ar: string | null; change_summary_en: string | null;
  script_ar: string | null; script_structure: ScriptStructure | null; final_line: string | null;
  // #154 — the persisted provider:model label that generated the shown script revision (script.model,
  // stamped by the writer at generation time). null = not recorded; topics persist no equivalent.
  script_model: string | null;
  delivery_notes: string | null; delivery_check: DeliveryCheck | null; script_revision: number | null;
  flags: string[] | null; needs_scholar_review: boolean; needs_native_review: boolean;
  current_outcome: "approved" | "changes_requested" | "rejected" | "pending";
  approval_count: number; remaining_approvals: number;
  remaining_assignments: ApprovalAssignment[];
  // #282 — authoritative per-token coverage for this target: each required token and the ONE effective
  // principal covering it (null when uncovered). Present only on an authoritative gate; null on legacy.
  coverage?: TokenCoverage[] | null;
  review_blockers: string[]; decisions: Decision[];
  directive: Directive | null; assets: Asset[] | null;
};
// #282 — one required assignment token and its covering effective principal (or null = uncovered).
export type TokenCoverage = { token_kind: "user" | "role" | "group"; token_key: string; normalized_token: string; covered_by: string | null };
export type Change = { slot_id: string; pillar_code: string; status: string; comment: string | null; revision: number };
export type Dropped = { slot_id: string; pillar_code: string; status: string; hook_text: string | null; reason: string | null };
export type StageState = { state: string; recommendation: string; warnings: string[]; confirm_warnings: string[];
  in_review: number; pending: number; approved: number; sent_back: number; rejected: number;
  awaiting: number; dropped: number; advanced: number; review_pending: number; gate_id: string | null;
  next_action: "generate" | "start_review" | "reviewing" | "ready_to_commit" | "awaiting_regeneration" | "complete" | "empty";
  generator: "ai" | "manual" | "external" | null; pending_input: number;
  approval_rule: string; approval_quorum: number; approval_assignments: ApprovalAssignment[] };
export type Revision = { revision: number; body: string | null; hook_text?: string | null; final_line?: string | null;
  feedback: string | null; change_summary_ar: string | null; change_summary_en: string | null;
  base_revision: number | null; approved: boolean;
  // #154 — present ONLY on script revisions (script.model; null = not recorded). Topic revisions
  // omit the key entirely because topics persist no model attribution — the UI must not imply parity.
  model?: string | null };
export type Gate = { gate_id: string; stage: string; status: string; quorum: string; rule_key: string; assignments: GateAssignment[]; targets: Target[];
  // #282 — an authoritative gate resolves ANY/ALL from frozen per-token coverage; a legacy (pre-migration)
  // gate keeps the historical count-based resolution and is surfaced truthfully as legacy.
  authoritative?: boolean; legacy?: boolean };
export type Round = { round_id: string; label: string | null; period_len_days: number; posts_per_day: number; slots: number; reserved: number; topic_proposed: number;
  schedule_approved: number; topic_approved: number; changes_requested: number; rejected: number; draft: number;
  approved: number; scheduled: number; phase: string };
export type Catalog = { glossary: Record<string, Record<string, { ar: string; en: string }>>; ui: Record<string, { ar: string; en: string }> };
export type StageDef = { key: string; gate: string; label: string; group: string; reviewStatuses: string[]; reworkArtifact?: "topic" | "script" | null; dam?: { stage: string; kind: string } };
// #49 — content-id derivation + bidirectional resolution live in the pure ./content-id module (so they
// are importable by the Playwright pure-logic tests without pulling React). Re-exported here so existing
// `@/lib/review-context` importers (review-item, review-surface) keep working unchanged.
export {
  contentIdParts, contentIdLabel, contentIdKey, resolveContentId,
  type ContentIdMode, type ContentIdTarget, type ContentIdResolution,
} from "./content-id";
export type ApprovalPolicy = {
  stage: string; rule_key: string; quorum: number; users: string[]; roles: string[]; groups: string[];
  assignments: ApprovalAssignment[]; source?: "db" | "yaml"; updated_by?: string;
};
export type ApprovalPolicyCatalog = { can_administer: boolean; policies: ApprovalPolicy[] };

export const GW = "/gw";
const LANG = "en";
export const APPROVERS = ["khal", "huda", "nour", "sheikh"];

// The current operating flow keeps the core delivery stages visible. Language/religious sign-off
// remain in the engine for later workflow-editor control, but are intentionally hidden here.
// #39 — display labels come from the single stage-identity source (lib/stages). `key`/`gate` remain the
// stable canonical identifiers; only the operator-facing `label` is presentation metadata.
export const STAGES: StageDef[] = [
  { key: "schedule", gate: "schedule_review", label: stageLabel("schedule"), group: "Content", reviewStatuses: ["RESERVED"] },
  { key: "topic", gate: "topic_review", label: stageLabel("topic"), group: "Content", reviewStatuses: ["TOPIC_PROPOSED"], reworkArtifact: "topic" },
  { key: "script", gate: "script_review", label: stageLabel("script"), group: "Content", reviewStatuses: ["DRAFT_ASSIGNED"], reworkArtifact: "script" },
  { key: "final", gate: "final_review", label: stageLabel("final"), group: "Sign-off", reviewStatuses: ["APPROVED_ASSIGNED"], reworkArtifact: "script" },
  { key: "production", gate: "production_review", label: stageLabel("production"), group: "Production", reviewStatuses: ["READY_FOR_PRODUCTION"], dam: { stage: "production", kind: "raw_cut" } },
  { key: "edit", gate: "edit_review", label: stageLabel("edit"), group: "Production", reviewStatuses: ["PRODUCED"], dam: { stage: "media_edit", kind: "edit" } },
  { key: "distribution", gate: "distribution_review", label: stageLabel("distribution"), group: "Production", reviewStatuses: ["EDITED"], dam: { stage: "distribution", kind: "post" } },
];
export const STAGE_GROUPS = ["Content", "Sign-off", "Production"];

export function approvalRuleLabel(rule: string) {
  return rule === "all" ? "AND" : rule === "any" ? "OR" : rule.toUpperCase();
}

export function approvalAssignmentLabel(a: ApprovalAssignment) {
  return `${a.assignment_kind}:${a.display_name_en || a.assignment_key}`;
}

function asCount(value: unknown) {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

export function roundActiveCount(round?: Partial<Round> | null) {
  if (!round) return 0;
  return asCount(round.reserved)
    + asCount(round.schedule_approved)
    + asCount(round.topic_proposed)
    + asCount(round.topic_approved)
    + asCount(round.draft)
    + asCount(round.approved)
    + asCount(round.scheduled);
}

export function roundApprovedCount(round?: Partial<Round> | null) {
  if (!round) return 0;
  return asCount(round.topic_approved) + asCount(round.approved);
}

// #55 — exported so the review surface can filter the visible feed by the SAME per-item outcome that
// produces the #47 disposition partition (clicked-count == filtered-visible-count reconciles by construction).
export function stagedOutcome(target: Target, approver: string): Target["current_outcome"] {
  if (target.current_outcome !== "pending") return target.current_outcome;
  const mine = target.decisions.filter((decision) => decision.approver_id === approver).slice(-1)[0];
  const staged = mine || target.decisions[target.decisions.length - 1];
  if (!staged) return "pending";
  if (staged.decision === "approve") return "approved";
  if (staged.decision === "request_change") return "changes_requested";
  if (staged.decision === "reject") return "rejected";
  return "pending";
}

// Every dashboard→gate call goes through the same-origin /gw proxy. Over the Tailscale funnel
// each round-trip is ~40x slower than localhost and the browser only has ~6 HTTP/1.1 connections
// to the host, so a stranded proxied request can hold a socket open indefinitely and starve later
// requests — including a review action's POST /rounds/{id}/rework, which then never reaches the
// gate (no card moves, no toast). Bounding every request with an abort timeout guarantees a stuck
// request releases its connection so the pool self-heals.
const GET_TIMEOUT_MS = 12000;
const WRITE_TIMEOUT_MS = 45000;
// how long a "just approved" acknowledgment lingers before it auto-clears (#24 item 2)
const JUST_APPROVED_TTL_MS = 8000;

async function gwFetch(p: string, init: RequestInit, timeoutMs: number) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    // #170 — forward this window's demo persona (if chosen) so the /gw proxy signs it instead of
    // the profile-wide cookie; window-scoped identity for multi-persona internal walkthroughs.
    const headers = new Headers(init.headers);
    const persona = getSessionPersona();
    if (persona) headers.set(PERSONA_HEADER, persona);
    const r = await fetch(`${GW}${p}`, { ...init, headers, signal: ctrl.signal });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  } finally {
    clearTimeout(timer);
  }
}

async function jget(p: string) {
  // Idempotent read: retry once if the first attempt timed out or the socket was starved. The
  // aborted attempt has already freed its connection, so the retry runs on a fresh socket and the
  // surface recovers instead of staying permanently stuck after a cold-load connection stampede.
  try {
    return await gwFetch(p, { cache: "no-store" }, GET_TIMEOUT_MS);
  } catch (e) {
    const transient = (e as Error)?.name === "AbortError" || e instanceof TypeError;
    if (transient) return await gwFetch(p, { cache: "no-store" }, GET_TIMEOUT_MS);
    throw e;
  }
}
async function jpost(p: string, body: unknown) {
  // Non-idempotent: never auto-retry (avoid double-rework / double-commit). Still bounded, so a
  // starved action surfaces an error toast the user can retry instead of hanging silently forever.
  return gwFetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, WRITE_TIMEOUT_MS);
}
async function jput(p: string, body: unknown) {
  return gwFetch(p, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, WRITE_TIMEOUT_MS);
}

// ---- the review state + actions (one engine, one source of truth) ----------
export type View = "inbox" | "overview" | "workflow" | "grid" | "calendar";

function useReviewState() {
  const [rounds, setRounds] = useState<Round[]>([]);
  // #280 — observational only: true until the FIRST /rounds fetch settles, so an empty-state can
  // truthfully distinguish "still loading runs" from "no runs exist". It observes the existing fetch;
  // it never changes what/when we request.
  const [roundsLoading, setRoundsLoading] = useState(true);
  // #280 (Codex P1) — true when the /rounds request FAILED, so the empty-state renders the truthful
  // "unavailable/error" variant instead of "no run" (a failed load can't establish whether runs
  // exist). Stays set until a subsequent /rounds load SUCCEEDS — never silently downgraded to no-run.
  const [roundsError, setRoundsError] = useState(false);
  const [roundSlots, setRoundSlots] = useState<RoundSlot[]>([]);   // #271 — all planned cells (calendar continuity)
  // #292 — the round's combined schedule token + its accepted server display codes. null/{} = a
  // legacy round with no governed mapping (V1 then derives codes exactly as it always has).
  const [scheduleToken, setScheduleToken] = useState<number | null>(null);
  const [displayCodes, setDisplayCodes] = useState<Record<string, string>>({});
  // #278 P1 — the run's FULL pinned eligibility (incl. zero-count frameworks) + persisted per-run mix,
  // from round_detail. The revision/run-mix controls offer any framework the run was planned against.
  const [roundPinned, setRoundPinned] = useState<{ name: string; framework_id: string | null }[]>([]);
  const [roundMix, setRoundMix] = useState<Record<string, number>>({});
  const [round, setRoundState] = useState<string>("");
  const [view, setViewState] = useState<View>("inbox");   // the active lens; inbox = the review surface
  const [roundStates, setRoundStates] = useState<Record<string, StageState>>({});  // per-stage states for the round (lenses)
  const [stageKeyState, setStageKeyState] = useState("schedule");
  const [gateRaw, setGate] = useState<Gate | null>(null);
  // #292 — decorate every target with the round's SERVER-ACCEPTED display code, in ONE place.
  // contentIdParts() prefers target.display_code over its derivation, so this single injection makes
  // the card label, the compact/expanded forms, search and sort all follow the accepted generation
  // together — they can never disagree with each other or with the server. A legacy round supplies
  // no codes, so every consumer falls back to the existing derivation untouched.
  // Declared here (not further down) because `gate` is read throughout this provider.
  const gate = useMemo(() => {
    if (!gateRaw || !Object.keys(displayCodes).length) return gateRaw;
    return {
      ...gateRaw,
      targets: gateRaw.targets.map((t) => ({ ...t, display_code: displayCodes[t.slot_id] ?? null })),
    };
  }, [gateRaw, displayCodes]);
  const [changes, setChanges] = useState<Change[]>([]);
  const [dropped, setDropped] = useState<Dropped[]>([]);   // reversible 'dropped' (REJECTED) items
  // #23 generation-mode visibility — the runtime writer mode from /health (authoritative: the process
  // actually decides which writer runs). "stub" => synthetic dev/test output; surfaced so stub/demo
  // generation is never silently misread as real content. "unavailable" if /health can't be read.
  const [genMode, setGenMode] = useState<"live" | "stub" | "unavailable" | null>(null);
  // #24 item 2 — short-lived "just approved" acknowledgment: an immediate per-item approval commits and
  // the card disappears (reads as "did it save? was data lost?"). We briefly surface the just-approved
  // slot in a transient lane (auto-expiring) so the approval is visibly confirmed and stays one click
  // from Restore. Purely client-side; no new backend/state — mirrors the recoverable Dropped lane.
  const [justApproved, setJustApproved] = useState<string[]>([]);
  const [stageState, setStageState] = useState<StageState | null>(null);  // lifecycle state + AI advisory
  const [genJob, setGenJob] = useState<{ done: number; total: number; status: string; label: string } | null>(null);
  const [approver, setApprover] = useState("khal");
  const [reviewerSyncing, setReviewerSyncing] = useState(false);
  const [approvers, setApprovers] = useState<Principal[]>([]);
  const [principalRoles, setPrincipalRoles] = useState<PrincipalRole[]>([]);
  const [principalGroups, setPrincipalGroups] = useState<PrincipalGroup[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [approvalAdmin, setApprovalAdmin] = useState(false);
  const [approvalPolicies, setApprovalPolicies] = useState<Record<string, ApprovalPolicy>>({});
  const [savingPolicyStage, setSavingPolicyStage] = useState<string | null>(null);
  const [cat, setCat] = useState<Catalog | null>(null);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState<Record<string, string>>({});
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});   // in-place edit of an awaiting item's change note
  const [openScript, setOpenScript] = useState<Set<string>>(new Set());
  const [history, setHistory] = useState<Set<string>>(new Set());
  const [revisions, setRevisions] = useState<Record<string, Revision[]>>({});
  const [reworkFromDraft, setReworkFromDraft] = useState<Record<string, string>>({});
  const [assetUri, setAssetUri] = useState<Record<string, string>>({});
  const [selectedSlotIds, setSelectedSlotIds] = useState<Set<string>>(new Set());
  const loadSeq = useRef(0);
  const stageContextRef = useRef<{ round: string; gate: string }>({ round: "", gate: "" });

  const stageKey = stageKeyState;
  const stage = STAGES.find((s) => s.key === stageKey)!;
  const isTopic = stageKey === "topic";
  const dam = stage.dam;
  const supportsRework = Boolean(stage.reworkArtifact);
  const reworkStage = stage.reworkArtifact || null;
  const g = useCallback((c: string, k: string) => cat?.glossary?.[c]?.[k]?.[LANG] || k, [cat]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const persistedView = (url.searchParams.get("view") || window.localStorage.getItem("tanaghom-view") || "") as View;
    const persistedStage = url.searchParams.get("stage") || window.localStorage.getItem("tanaghom-stage") || "";
    const restoredStage = (persistedStage && STAGES.some((stage) => stage.key === persistedStage)) ? persistedStage : stageKeyState;
    if (persistedStage && STAGES.some((stage) => stage.key === persistedStage)) {
      setStageKeyState(persistedStage);
    }
    // #15 — restore the saved view only if it is valid for the (restored) stage, else fall back to inbox,
    // so a reload never lands a content review stage on a non-card view (e.g. a stale saved calendar).
    if (persistedView && ["inbox", "overview", "workflow", "grid", "calendar"].includes(persistedView)) {
      setViewState(coerceViewForStage(persistedView, restoredStage));
    }
  }, []);

  useEffect(() => {
    stageContextRef.current = { round, gate: stage.gate };
  }, [round, stage.gate]);

  useEffect(() => { jget(`/i18n`).then(setCat).catch(() => {}); }, []);
  // #93/#50 — load the managed content-format registry once; map each format NAME to its actual selected
  // framework (name + component step labels) so topic cards surface the real framework, not a placeholder.
  // Read-only, best-effort — a failure never blocks the review surface.
  const [frameworks, setFrameworks] = useState<Record<string, Framework>>({});
  useEffect(() => {
    jget(`/content-formats`).then((res: unknown) => {
      const list = (Array.isArray(res) ? res : ((res as { formats?: unknown[] })?.formats || [])) as Array<Record<string, unknown>>;
      const map: Record<string, Framework> = {};
      for (const raw of list) {
        const name = String(raw.name || "");
        if (!name) continue;
        const pr = ((raw.active_version as Record<string, unknown>)?.production_rules || {}) as Record<string, unknown>;
        const structure = Array.isArray(pr.structure) ? (pr.structure as Array<Record<string, unknown>>) : [];
        const components = structure.map((s) => String(s.label || s.step || "")).filter(Boolean);
        // #149 — the ordered step keys + their labels, straight from the registry structure.
        const structureOrder: string[] = [];
        const structureLabels: Record<string, string> = {};
        for (const s of structure) {
          const step = String(s.step || "").trim();
          if (!step) continue;
          structureOrder.push(step);
          structureLabels[step] = String(s.label || step).trim();
        }
        map[name] = {
          name,
          frameworkName: (pr.framework_name as string) || null,
          summary: (pr.framework_summary as string) || null,
          components,
          structureOrder,
          structureLabels,
          frameworkStatus: (pr.framework_status as string) || null,
        };
      }
      setFrameworks(map);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    jget(`/principals?kind=user&active=true&module=content`)
      .then((rows: Principal[]) => setApprovers(rows))
      .catch(() => {});
  }, []);
  // #215 — stale-response guard for persona-scoped authority loaders. These fetches are signed
  // with the WINDOW persona, and a response that started under a superseded persona (e.g. the
  // fresh-window default fired before the operator picked one) can resolve AFTER the current
  // persona's refresh — it must never overwrite newer authority state. Each call takes a
  // monotonically increasing sequence at START; only the newest call may commit
  // (last-STARTED wins, never last-finished). `can_administer` is persona-derived authority,
  // so the catalog loader shares the guard.
  const approvalCatalogSeq = useRef(0);
  const loadApprovalCatalog = useCallback(async () => {
    const seq = ++approvalCatalogSeq.current;
    const [roles, groups, policyCatalog] = await Promise.all([
      jget(`/principal-roles?active=true&module=content`),
      jget(`/principal-groups?active=true&module=content`),
      jget(`/approval-policies`),
    ]) as [PrincipalRole[], PrincipalGroup[], ApprovalPolicyCatalog];
    if (seq !== approvalCatalogSeq.current) return;   // superseded — discard, never overwrite
    setPrincipalRoles(roles);
    setPrincipalGroups(groups);
    setApprovalAdmin(policyCatalog.can_administer);
    setApprovalPolicies(Object.fromEntries(policyCatalog.policies.map((p) => [p.stage, p])) as Record<string, ApprovalPolicy>);
  }, []);
  useEffect(() => {
    // Defer the non-critical admin catalogue (3 concurrent /gw reads) off the cold-load critical
    // path so rounds + the review surface win the initial connection race over the funnel. Without
    // this, the admin trio was among the requests stranded during the cold-load stampede.
    const t = setTimeout(() => { loadApprovalCatalog().catch(() => {}); }, 1500);
    return () => clearTimeout(t);
  }, [loadApprovalCatalog]);
  // #170 — per-window persona entry (#13 S1). This window's sessionStorage persona wins over the
  // profile-wide cookie; a fresh internal browser (no persona, no explicit cookie, not client-trial)
  // gets the demo persona entry surface before working in the dashboard. null = still deciding.
  const [personaEntry, setPersonaEntry] = useState<boolean | null>(null);
  // #190 — IAM state: mode "oidc" disables every persona/demo identity surface; identity comes
  // only from the authenticated BFF session (server-enforced at /gw regardless of this state).
  const [iam, setIam] = useState<{
    mode: boolean; authenticated?: boolean; unbound?: boolean;
    display?: string | null; email?: string | null;
  } | null>(null);
  useEffect(() => {
    // #180/#190 — the SERVER decides the surface AND the identity mode; client state (persona
    // sessionStorage, reviewer cookie) is consulted only in demo mode.
    fetchRuntime()
      .then(async (rt) => {
        if (rt?.identity === "oidc") {
          setPersonaEntry(false);
          const s = await fetch("/api/auth/session", { cache: "no-store" })
            .then((r) => r.json()).catch(() => null);
          setIam({ mode: true, authenticated: Boolean(s?.authenticated),
                   unbound: Boolean(s?.unbound), display: s?.display ?? null, email: s?.email ?? null });
          if (s?.principal_id) setApprover(s.principal_id);
          return;
        }
        setIam({ mode: false });
        const persona = getSessionPersona();
        if (persona) {
          setApprover(persona);
          setPersonaEntry(false);
          return;
        }
        if (rt?.surface === "client-trial") { setPersonaEntry(false); return; }
        const j = await fetch("/api/reviewer", { cache: "no-store" })
          .then((r) => r.json()).catch(() => null);
        if (j?.reviewer) setApprover(j.reviewer);
        setPersonaEntry(!j?.explicit);
      })
      // Convenience surface, not a security gate (enforcement is server-side, #10/#190) — fail open.
      .catch(() => { setPersonaEntry(false); setIam({ mode: false }); });
  }, []);
  const pendingApprovalsSeq = useRef(0);
  const loadPendingApprovals = useCallback(async () => {
    // #215 — same stale-response guard: the pre-persona default fetch (whose payload can be
    // large and slow) must never clobber the picked persona's approval queue
    const seq = ++pendingApprovalsSeq.current;
    const rows: PendingApproval[] = await jget(`/me/pending-approvals`);
    if (seq !== pendingApprovalsSeq.current) return;   // superseded — discard, never overwrite
    setPendingApprovals(rows);
  }, []);
  // #280 (Codex P1) — loadRounds OWNS the loading/error lifecycle for the rounds source, for EVERY
  // call site (mount + all refetches). The error is set on any failed attempt and cleared ONLY after a
  // successful load — so it is preserved through failed retries and never optimistically cleared on
  // entry. Self-contained: it never rejects, so no caller has to remember to handle it.
  const roundsSeq = useRef(0);
  const loadRounds = useCallback(async () => {
    // #286 — monotonic stale-response guard (the established #215 pattern, mirroring
    // loadPendingApprovals/loadApprovalCatalog): only the LATEST invocation may commit rounds /
    // roundsLoading / roundsError, so an older FAILED request can never overwrite a newer SUCCESSFUL
    // one (nor vice-versa) when overlapping loads resolve out of order.
    const seq = ++roundsSeq.current;
    const latest = () => seq === roundsSeq.current;
    try {
      const rs: Round[] = await jget(`/rounds`);
      if (!latest()) return;   // superseded by a newer load — discard this stale success
      setRounds(rs);
      const active = rs.filter((r) => roundActiveCount(r) > 0);
      setRoundState((cur) => {
        if (cur && rs.some((round) => round.round_id === cur)) return cur;
        const persisted = typeof window === "undefined"
          ? ""
          : (new URL(window.location.href).searchParams.get("round")
            || window.localStorage.getItem("tanaghom-round")
            || "");
        if (persisted && rs.some((round) => round.round_id === persisted)) return persisted;
        return active[active.length - 1]?.round_id ?? rs[rs.length - 1]?.round_id ?? "";
      });
      setRoundsError(false);   // clear the load error ONLY after a successful (latest) load
    } catch (e) {
      if (!latest()) return;   // superseded by a newer load — discard this stale failure
      setRoundsError(true);    // set/preserve on a failed LATEST attempt (initial or retry)
      setToast({ kind: "err", msg: String(e) });
    } finally {
      if (latest()) setRoundsLoading(false); // only the latest invocation settles the load flag
    }
  }, []);
  useEffect(() => { void loadRounds(); }, [loadRounds]);
  // #271 — the run's COMPLETE planned slot set (round_detail), independent of the active gate, so the
  // calendar keeps every positional cell (with lifecycle status) after Schedule approval.
  const loadRoundSlots = useCallback(async () => {
    if (!round) {
      setRoundSlots([]); setRoundPinned([]); setRoundMix({});
      setScheduleToken(null); setDisplayCodes({});
      return;
    }
    try {
      const d = await jget(`/rounds/${round}`);
      setRoundSlots((d?.slots as RoundSlot[]) || []);
      setRoundPinned((d?.pinned_eligible_formats as { name: string; framework_id: string | null }[]) || []);
      setRoundMix((d?.format_mix as Record<string, number>) || {});
    } catch { setRoundSlots([]); setRoundPinned([]); setRoundMix({}); }
    // #292 — V1 compatibility support (additive). Two reasons this load exists:
    //   1. the server-issued schedule_token is REQUIRED on a schedule revision (no legacy bypass),
    //      so V1 must hold the current one or its revisions are correctly rejected with 409;
    //   2. when a round HAS an accepted mapping generation, the server display_code is
    //      authoritative and V1 must prefer it — a governed reorder renumbers presentation, and V1
    //      must never keep showing a code the server no longer accepts.
    // A LEGACY round (no generation) returns legacy:true / token 0 and no positions, so V1 keeps
    // deriving exactly as before. This is the only #292 behaviour V1 gains.
    try {
      const m = await jget(`/rounds/${round}/schedule-mapping`);
      setScheduleToken(typeof m?.schedule_token === "number" ? m.schedule_token : null);
      const codes: Record<string, string> = {};
      for (const p of (m?.positions as { slot_id: string; display_code: string }[]) || []) {
        codes[p.slot_id] = p.display_code;
      }
      setDisplayCodes(codes);
    } catch {
      // A failed mapping read must not fabricate codes: fall back to derivation and force the
      // caller to refresh before a revision (a null token is rejected server-side, never guessed).
      setScheduleToken(null); setDisplayCodes({});
    }
  }, [round]);
  useEffect(() => {
    // #280 — clear the prior run's cells SYNCHRONOUSLY on round change, before the refetch resolves,
    // so the continuity calendar (which reads roundSlots directly) never paints the previous run's
    // slots during the fetch window. Restores the freshness guard the gate-target path had implicitly.
    setRoundSlots([]); setRoundPinned([]); setRoundMix({});
    loadRoundSlots().catch(() => {});
  }, [loadRoundSlots]);
  // resolve the runtime generation mode once, from the authoritative /health writer_mode (read-only)
  useEffect(() => {
    jget("/health")
      .then((h: { writer_mode?: string }) => {
        const wm = h?.writer_mode;
        setGenMode(wm === "live" ? "live" : wm ? "stub" : "unavailable");
      })
      .catch(() => setGenMode("unavailable"));
  }, []);

  // the open review for THIS round+stage comes from stage_state (the ACTIVE gate; orphan/duplicate
  // gates are ignored + auto-superseded server-side) — so the surface never binds to a stale gate.
  const fetchStageSnapshot = useCallback(async (roundId: string, gateName: string, seq: number) => {
    const ss: StageState = await jget(`/rounds/${roundId}/stages/${gateName}/state`);
    if (seq !== loadSeq.current) return;
    const nextGate = ss.gate_id ? await jget(`/gates/${ss.gate_id}`) : null;
    if (seq !== loadSeq.current) return;
    if (stageContextRef.current.round !== roundId || stageContextRef.current.gate !== gateName) return;
    setStageState(ss);
    setGate(nextGate);
  }, []);
  const reassertStageSnapshot = useCallback((roundId: string, gateName: string, delays = [600, 1800, 5000]) => {
    delays.forEach((delay) => {
      window.setTimeout(() => {
        if (stageContextRef.current.round !== roundId || stageContextRef.current.gate !== gateName) return;
        const seq = ++loadSeq.current;
        fetchStageSnapshot(roundId, gateName, seq).catch(() => {});
      }, delay);
    });
  }, [fetchStageSnapshot]);
  const load = useCallback(async (retryDelays: number[] = []) => {
    if (!round) { setGate(null); setStageState(null); return; }
    const seq = ++loadSeq.current;
    await fetchStageSnapshot(round, stage.gate, seq);
    retryDelays.forEach((delay) => {
      window.setTimeout(() => {
        fetchStageSnapshot(round, stage.gate, seq).catch(() => {});
      }, delay);
    });
  }, [fetchStageSnapshot, round, stage.gate]);
  useEffect(() => { load([600, 1800, 5000]).catch((e) => setToast({ kind: "err", msg: String(e) })); }, [load]);

  const loadChanges = useCallback(async () => {
    if (!round || !reworkStage) { setChanges([]); return; }
    setChanges(await jget(`/rounds/${round}/changes?stage=${reworkStage}`));
  }, [round, reworkStage]);
  useEffect(() => { loadChanges().catch(() => {}); }, [loadChanges, gate]);

  const loadDropped = useCallback(async () => {
    if (!round) { setDropped([]); return; }
    setDropped(await jget(`/rounds/${round}/dropped`));
  }, [round]);
  useEffect(() => { loadDropped().catch(() => {}); }, [loadDropped, gate]);

  // #179 — the durable post-commit trail for THIS stage: what was approved & advanced here and
  // where it is now. Server-derived from committed gate state (mirrors the Dropped lane), so it
  // survives reloads and never depends on the short-lived "just approved" client acknowledgment.
  const [advancedTrail, setAdvancedTrail] = useState<AdvancedItem[]>([]);
  const loadAdvancedTrail = useCallback(async () => {
    if (!round) { setAdvancedTrail([]); return; }
    setAdvancedTrail(await jget(`/rounds/${round}/stages/${stage.gate}/advanced`));
  }, [round, stage.gate]);
  useEffect(() => { loadAdvancedTrail().catch(() => {}); },
    // refresh on gate change (commit closes the gate) and on per-item immediate approvals
    [loadAdvancedTrail, gate, stageState?.advanced]);
  useEffect(() => { loadPendingApprovals().catch(() => {}); }, [loadPendingApprovals, approver, gate]);

  // #200 (pub.v1) — governed manual publication recording, distribution stage only. Server truth:
  // eligibility + attest authority are decided by the gate API on every call; this state is a read
  // model plus two bounded actions. The operation key is generated by the DIALOG once at open and
  // reused across retries, so a double-click or a retried request converges on ONE recorded truth.
  const [publications, setPublications] = useState<PublicationRecord[]>([]);
  const [platforms, setPlatforms] = useState<PlatformOption[]>([]);
  const loadPublications = useCallback(async () => {
    if (!round || stage.key !== "distribution") { setPublications([]); return; }
    setPublications(await jget(`/publications?round_id=${round}`));
  }, [round, stage.key]);
  // #237 Slice A — lazy, read-only inspection of ONE completed-trail item (fetched on expansion,
  // never with the trail list). Same bounded+retry /gw read path as every other surface read.
  const inspectSlot = useCallback(
    (slotId: string) => jget(`/slots/${slotId}/inspect`) as Promise<SlotInspect>, []);
  // #250 — read-only SDAM readiness state for one slot (persisted truth only) and the lazy,
  // explicitly-invoked provider-neutral Edit-handoff read (existing #244 authorization).
  const sdamState = useCallback(
    (slotId: string) => jget(`/slots/${slotId}/sdam`) as Promise<SlotSdam>, []);
  const sdamHandoff = useCallback(
    (bindingId: string) => jget(`/sdam/bindings/${bindingId}/handoff`) as Promise<SdamHandoff>, []);
  // #259 S2 — governed completed-edit registration (explicit action; server re-checks the
  // audit-verified S1 pin + trusted principal). Non-idempotent write -> never auto-retried.
  const sdamRegisterEdit = useCallback(
    (slotId: string) => jpost(`/slots/${slotId}/sdam/register-edit`, {}), []);
  useEffect(() => { loadPublications().catch(() => {}); },
    [loadPublications, gate, stageState?.advanced]);
  useEffect(() => {
    if (stage.key !== "distribution") return;
    jget(`/platforms`).then(setPlatforms).catch(() => {});
  }, [stage.key]);
  const recordPublication = (payload: { slot_id: string; platform_key: string;
    idempotency_key: string; destination?: string; url?: string }) => run(async () => {
    // two contract steps, one operator action: reserve/replay the intent (idempotent on the
    // dialog's operation key), then attest the manual outcome. If the outcome step fails midway,
    // the intent stays visible as "ready to record" and completePublication finishes it.
    const intent: PublicationRecord = await jpost(`/publications`, payload);
    if (!intent.publication_occurrence_id) {
      await jpost(`/publications/${intent.publication_intent_id}/manual-outcome`,
        { outcome: "published", url: payload.url || undefined });
    }
    ok("Publication recorded.");
    await loadPublications();
  });
  const completePublication = (intentId: string, url?: string) => run(async () => {
    await jpost(`/publications/${intentId}/manual-outcome`, { outcome: "published", url });
    ok("Publication recorded.");
    await loadPublications();
  });

  const roundInfo = rounds.find((x) => x.round_id === round) || null;

  // per-stage lifecycle states for the whole round — feeds the Overview + Workflow lenses (real
  // engine data only). Fetched when a lens is active, refreshed on round/gate change.
  const loadStates = useCallback(async () => {
    if (!round) { setRoundStates({}); return; }
    const pairs = await Promise.all(STAGES.map(async (s) => {
      try { return [s.gate, await jget(`/rounds/${round}/stages/${s.gate}/state`)] as const; }
      catch { return [s.gate, null] as const; }
    }));
    setRoundStates(Object.fromEntries(pairs.filter(([, v]) => v)) as Record<string, StageState>);
  }, [round]);
  useEffect(() => { if (view !== "inbox") loadStates().catch(() => {}); }, [view, loadStates, gate]);

  // #175 — can the ACTIVE persona decide the current open gate? Server truth only, never client-side
  // authority inference: an empty assignment snapshot means the engine restricts no one; a direct
  // user assignment mirrors the engine's exact-id match; role/group membership is NOT in the client
  // read model (member counts only), so it is answered by /me/pending-approvals — computed by the
  // backend with the same membership tables the decide path enforces. UI prevention is convenience
  // only; the API still rejects non-assigned decisions at decide time (#10).
  const canDecideGate = useMemo(() => {
    if (!gate || gate.status !== "open") return true;
    const assignments = gate.assignments || [];
    if (!assignments.length) return true;
    if (assignments.some((a) => a.assignment_kind === "user"
      && (a.assignment_key === approver || a.resolved_principal_id === approver))) return true;
    return pendingApprovals.some((p) => p.gate_id === gate.gate_id);
  }, [gate, pendingApprovals, approver]);
  // #175 — client-safe wording for who CAN decide the current gate (display names over raw tokens).
  const gateRequirements = useMemo(() => {
    if (!gate?.assignments?.length) return [] as string[];
    return gate.assignments.map((a) => a.assignment_kind === "user"
      ? (a.display_name_en || a.assignment_key)
      : `the "${a.display_name_en || a.assignment_key}" ${a.assignment_kind}`);
  }, [gate]);
  // #175 — a just-opened gate isn't in the mount-time pending list; refresh it when the gate (or the
  // acting persona) changes so assigned-vs-not is judged against fresh server truth.
  useEffect(() => {
    if (gate?.gate_id) loadPendingApprovals().catch(() => {});
  }, [gate?.gate_id, approver, loadPendingApprovals]);

  // #175 — assignment denials must never surface as raw engine text. UI prevention makes this rare
  // (stale state / races only); the backend behavior itself is untouched — it still rejects + audits.
  const clientSafeError = (raw: string) => {
    if (!/not configured for|not_assigned/i.test(raw)) return raw;
    const who = approvers.find((p) => p.principal_id === approver)?.display_name_en || approver;
    const req = gateRequirements.length ? ` Deciding here requires ${gateRequirements.join(" or ")}.` : "";
    return `You're acting as ${who}, who isn't assigned to decide at this stage.${req} Switch to an assigned persona (Reviewer menu) or update the workflow assignments.`;
  };
  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); } catch (e) { setToast({ kind: "err", msg: clientSafeError(String(e)) }); } finally { setBusy(false); } };
  const ok = (msg: string) => setToast({ kind: "ok", msg });
  const isCurrentStageContext = useCallback((roundId: string, gateName: string) => {
    return stageContextRef.current.round === roundId && stageContextRef.current.gate === gateName;
  }, []);
  const setView = (v: View) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("tanaghom-view", v);
      const url = new URL(window.location.href);
      url.searchParams.set("view", v);
      window.history.replaceState({}, "", url);
    }
    setViewState(v);
  };
  // clear ALL stage-scoped state on round change so the surface never shows the previous round's
  // disposition/cards while the new round's data loads (was a visible stale-state race).
  const setRound = (v: string) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("tanaghom-round", v);
      const url = new URL(window.location.href);
      if (v) url.searchParams.set("round", v);
      else url.searchParams.delete("round");
      window.history.replaceState({}, "", url);
    }
    stageContextRef.current = { round: v, gate: stage.gate };
    setRoundState(v);
    setGate(null);
    setStageState(null);
    setChanges([]);
    setDropped([]);
    setJustApproved([]);
    setRoundStates({});
    setSelectedSlotIds(new Set());
    setToast(null);   // clear any toast from the previous round so it doesn't leak into the new round context
    if (v) reassertStageSnapshot(v, stage.gate);
  };
  const setStageKey = (v: string) => {
    // Re-selecting the current stage must not wipe its already-loaded review state: the clears below
    // rely on the [loadChanges, gate] effect to refetch, which only re-fires when the stage (reworkStage)
    // or gate actually changes. Navigating to the stage you are already on (e.g. after a reload) would
    // otherwise blank `changes`/`dropped` with no refetch — hiding the awaiting-regeneration affordance.
    if (v === stageKey) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem("tanaghom-stage", v);
      const url = new URL(window.location.href);
      url.searchParams.set("stage", v);
      window.history.replaceState({}, "", url);
    }
    const nextStage = STAGES.find((s) => s.key === v) || stage;
    stageContextRef.current = { round, gate: nextStage.gate };
    setStageKeyState(v);
    setGate(null);
    setStageState(null);
    setChanges([]);
    setDropped([]);
    setJustApproved([]);
    setSelectedSlotIds(new Set());
    setChanging({});
    if (round) reassertStageSnapshot(round, nextStage.gate);
  };
  const refresh = useCallback(async () => { await load(); await loadChanges(); await loadRounds(); await loadRoundSlots(); }, [load, loadChanges, loadRounds, loadRoundSlots]);
  // register a just-approved slot in the transient acknowledgment lane, auto-clearing after the TTL
  const markJustApproved = useCallback((slotId: string) => {
    setJustApproved((cur) => (cur.includes(slotId) ? cur : [...cur, slotId]));
    window.setTimeout(() => setJustApproved((cur) => cur.filter((id) => id !== slotId)), JUST_APPROVED_TTL_MS);
  }, []);
  const dismissJustApproved = useCallback((slotId: string) => {
    setJustApproved((cur) => cur.filter((id) => id !== slotId));
  }, []);
  const refreshBurst = useCallback((delays = [1200, 3000, 7000, 15000]) => {
    delays.forEach((delay) => {
      window.setTimeout(() => {
        load().catch(() => {});
        loadChanges().catch(() => {});
        loadRounds().catch(() => {});
      }, delay);
    });
  }, [load, loadChanges, loadRounds]);
  const resumeReviewIfNeeded = useCallback(async () => {
    if (!round) return false;
    const ss: StageState = await jget(`/rounds/${round}/stages/${stage.gate}/state`);
    if (!ss.gate_id && ss.review_pending > 0) {
      await jpost(`/gates`, { stage: stage.gate, round_id: round });
      return true;
    }
    return false;
  }, [round, stage.gate]);
  const saveApprovalPolicy = useCallback(async (stageName: string, policy: Pick<ApprovalPolicy, "rule_key" | "users" | "roles" | "groups">) => {
    setSavingPolicyStage(stageName);
    try {
      const updated: ApprovalPolicy = await jput(`/stages/${stageName}/approval-policy`, {
        rule: policy.rule_key,
        users: policy.users,
        roles: policy.roles,
        groups: policy.groups,
      });
      setApprovalPolicies((m) => ({ ...m, [stageName]: updated }));
      await loadApprovalCatalog();
      if (round) await loadStates();
      if (stage.gate === stageName) await load();
      ok(`Approval policy updated for ${stageName}.`);
    } finally {
      setSavingPolicyStage(null);
    }
  }, [load, loadApprovalCatalog, loadStates, round, stage.gate]);

  // start a run from the UI: plan a round scaled to days × posts/day, then select it
  // #276 — the current baseline eligibility policy for the new-run surface (the eligible frameworks the
  // operator allocates within). Resolved from the governed policy seam, never a hard-coded list.
  const getBaselineEligibility = useCallback(async () => {
    return (await jget(`/baseline-eligibility`)) as {
      policy: { policy_id: string; generation: number };
      eligible: { name: string; framework_id: string; version_id: string }[];
    };
  }, []);
  const plan = useCallback(async (days: number, postsPerDay: number, label?: string,
                                  formatMix?: Record<string, number>) => {
    // #276 — format_mix is required by the server (no default allocation); the dialog supplies it.
    const r = await jpost(`/rounds`, { days, posts_per_day: postsPerDay, label, format_mix: formatMix });
    await loadRounds();
    setView("calendar");
    setStageKey("schedule");
    setRound(r.round_id);
    return r.round_id as string;
  }, [loadRounds, setRound]);
  // #271 — governed single-slot schedule revision: proposes day/time/format/topic-guidance changes;
  // the server returns only that slot to Schedule review (existing reviewer authority). Refresh after.
  const reviseSchedule = useCallback(async (slotId: string, changes: Record<string, unknown>) => {
    try {
      // #292 — the server-issued combined token is REQUIRED (no legacy bypass): without it a
      // revision could silently overwrite a concurrently accepted mapping. A stale token is a
      // typed 409 the operator resolves by refreshing — never a silent overwrite.
      await jpost(`/slots/${slotId}/schedule-revision`, { changes, schedule_token: scheduleToken });
      await load(); await loadRoundSlots();
      setToast({ kind: "ok", msg: `Slot ${slotId} returned to Schedule review` });
    } catch (e) {
      const stale = /409|stale_schedule_token|stale/i.test(String(e));
      if (stale) await loadRoundSlots();     // refresh the token/codes so a retry is against truth
      setToast({
        kind: "err",
        msg: stale
          ? "The schedule changed while you were editing — refreshed to the current version. Review it and try again."
          : String(e),
      });
      throw e;
    }
  }, [load, loadRoundSlots, scheduleToken]);

  // #278 P1 — pre-Schedule-approval run-level mix revision through the planning surface. Validates the
  // exact total against the run's pinned eligibility server-side and reconciles ONLY uncommitted
  // (RESERVED) slots; once any slot is committed the server fails closed and the error surfaces here.
  const reviseRunMix = useCallback(async (formatMix: Record<string, number>) => {
    try {
      const res = await jpost(`/rounds/${round}/format-mix`, { format_mix: formatMix });
      await load(); await loadRoundSlots();
      setToast({ kind: "ok", msg: `Run mix updated — ${res?.reconciled_slots ?? 0} slot(s) reconciled` });
    } catch (e) {
      setToast({ kind: "err", msg: String(e) });
      throw e;
    }
  }, [round, load, loadRoundSlots]);

  // Trigger generation as a background job, then converge on completion. The AUTHORITATIVE completion
  // signal is the DB stage state (the stage leaves the "generate" action once items are written), NOT
  // the in-memory /jobs registry: that registry is ephemeral (evicted past a cap, lost on API restart,
  // per-worker) so GET /jobs can 404 / time out / stick at "running" under load while generation still
  // finishes in the DB. We use /jobs only for the progress bar, and resurface the review from stage
  // state regardless — so the UI never dead-ends on a flaky job poll.
  const generate = () => run(async () => {
    const genRound = round;
    const genGate = stage.gate;
    const r = await jpost(`/rounds/${genRound}/stages/${genGate}/generate`, {});
    setGenJob({ done: 0, total: r.total, status: "running", label: "Generating" });

    const deadline = Date.now() + 120_000;   // hard backstop
    let settled = false;
    let jobFinishedAt: number | null = null;

    const stageReady = async (): Promise<boolean> => {
      try {
        const ss: StageState = await jget(`/rounds/${genRound}/stages/${genGate}/state`);
        return ss.next_action !== "generate";   // items written → stage advanced past generation
      } catch {
        return false;
      }
    };

    const settle = async (kind: "done" | "error", opts: { autoOpen?: boolean; errorMsg?: string } = {}) => {
      if (settled) return;
      settled = true;
      setGenJob(null);
      const current = isCurrentStageContext(genRound, genGate);
      if (kind === "error") {
        if (current) await load();
        await loadRounds();
        setToast({ kind: "err", msg: `Generation failed: ${opts.errorMsg}` });
        return;
      }
      if (current) {
        // Normal completion (the job poll confirmed "done") leaves the "Start review" (open-gate) control
        // for the operator — the standard two-stage flow. But when we only learned generation finished from
        // the DB fallback (the job poll was unavailable / dead-ended), open the review directly so the
        // operator is never stranded without a visible next action.
        if (opts.autoOpen) await resumeReviewIfNeeded();
        await load();
        await loadRounds();
        await loadPendingApprovals();
      } else {
        await loadRounds();
      }
      ok(`Generated ${r.total} item(s) — ready to review.`);
      refreshBurst();
    };

    const poll = async () => {
      if (settled) return;
      let jobsReachable = true;
      let jobFinished = false;
      try {
        const js = await jget(`/jobs/${r.job_id}`);
        setGenJob({ done: js.done, total: js.total, status: js.status, label: "Generating" });
        if (js.status === "error") {
          // #207 — the registry's raw error is DIAGNOSTIC text (endpoints, stack traces, provider
          // detail) and stays BACKEND-ONLY (job registry + API logs). The client logs a fixed
          // line with the non-sensitive job id so support can correlate; the user sees fixed,
          // retryable product wording. Raw detail never enters any client surface.
          console.warn(`generation job ${r.job_id} failed — see server logs / the job registry for diagnostics`);
          await settle("error", { errorMsg: "something went wrong and nothing was changed. You can generate again." });
          return;
        }
        jobFinished = js.status !== "running";
      } catch {
        jobsReachable = false;   // /jobs 404 / timeout / evicted — the review must resurface from the DB
      }
      if (jobFinished) {
        // #207 — a finished job is NOT success by itself: the writer records per-item failures
        // and returns normally, so a "done" job can carry ZERO persisted items (the #204 false
        // success). Success settles ONLY on positive persisted stage evidence; a finished job
        // whose stage still offers "generate" gets a short grace for commit/read lag, then
        // settles as a truthful, retryable failure — never an empty success, never an
        // auto-opened review.
        if (await stageReady()) { await settle("done"); return; }   // evidence-backed completion
        if (jobFinishedAt === null) jobFinishedAt = Date.now();
        if (Date.now() - jobFinishedAt > 5_000) {
          await settle("error", { errorMsg: "no items were produced, so nothing changed. You can generate again." });
          return;
        }
      } else if (await stageReady()) {
        // The DB says generation finished. If the job poll is reachable (just lagging behind the DB, or
        // stuck at "running"), keep the standard two-stage "Start review" control; only when the poll is
        // UNAVAILABLE do we open the review directly, so a dead-ended poll never strands the operator.
        await settle("done", { autoOpen: !jobsReachable });
        return;
      }
      if (Date.now() > deadline) {
        settled = true;
        setGenJob(null);
        setToast({ kind: "err", msg: "Generation is taking longer than expected — refreshing the stage." });
        refreshBurst([0, 2000, 5000]);
        return;
      }
      setTimeout(poll, 1000);
    };
    setTimeout(poll, 800);
  });

  // business lexicon: no "gate" wording — "start review" loads the queue for this stage
  const openGate = () => run(async () => {
    const actionRound = round;
    const actionGate = stage.gate;
    if (stage.key === "schedule") setView("calendar");
    await jpost(`/gates`, { stage: stage.gate, round_id: round });
    if (isCurrentStageContext(actionRound, actionGate)) await load();
    await loadRounds();
    ok(`Review started for ${stage.label} · ${round}.`);
  });

  const decide = (decision: string, slot_ids: string[], notes?: string, mode: "immediate" | "deferred" = "immediate") => run(async () => {
    if (!gate || !slot_ids.length) return;
    const actionRound = round;
    const actionGate = stage.gate;
    setSelectedSlotIds((current) => {
      const next = new Set(current);
      slot_ids.forEach((slotId) => next.delete(slotId));
      return next;
    });
    await jpost(`/gates/${gate.gate_id}/decide`, { decision, slot_ids, notes });
    setChanging((current) => {
      if (!slot_ids.some((slotId) => slotId in current)) return current;
      const next = { ...current };
      slot_ids.forEach((slotId) => { delete next[slotId]; });
      return next;
    });
    if (mode === "deferred") {
      if (isCurrentStageContext(actionRound, actionGate)) await load();
      if (decision === "request_change")
        ok(`Change request saved for ${slot_ids.join(", ")}. Apply it when you commit the batch.`);
      else if (decision === "reject")
        ok(`Drop saved for ${slot_ids.join(", ")}. Apply it when you commit the batch.`);
      else ok(`Approval saved for ${slot_ids.join(", ")}.`);
      return;
    }
    const res = await jpost(`/gates/${gate.gate_id}/resolve`, { slot_ids });
    const outcome = (res.outcomes || {})[slot_ids[0]];
    // Toast immediately from the resolve result and let the run() wrapper RELEASE the global busy flag
    // right here — the mutation is done. The display refresh (item leaving the queue, awaiting/dropped
    // lanes, round summary) then runs in the BACKGROUND rather than holding every other card's actions
    // disabled across the whole 5-fetch cascade — that cascade, under load, is what made the remaining
    // topic cards read as "inert" after one item was sent back.
    if (outcome === "approved") {
      ok(`Applied ${decision === "approve" ? "approval" : "decision"} for ${slot_ids[0]}.`);
      if (decision === "approve") slot_ids.forEach(markJustApproved);   // #24: transient just-approved ack
    } else if (outcome === "changes_requested") {
      ok(`Sent ${slot_ids[0]} back for changes — regenerate when you are ready.`);
    } else if (outcome === "rejected") {
      ok(`Dropped ${slot_ids[0]} — recoverable from the Dropped lane.`);
    } else {
      ok(`Recorded ${decision} on ${slot_ids[0]} — waiting for the remaining approver(s).`);
    }
    void (async () => {
      if (isCurrentStageContext(actionRound, actionGate)) { await load(); await loadChanges(); await loadDropped(); }
      await loadRounds();
      await loadPendingApprovals();
      if (outcome === "changes_requested") refreshBurst();
    })().catch(() => {});
  });

  // pre-commit undo (un-decide): clear a recorded decision before submitting
  const undecide = (slot_id: string) => run(async () => {
    if (!gate) return;
    const actionRound = round;
    const actionGate = stage.gate;
    setSelectedSlotIds((current) => {
      const next = new Set(current);
      next.delete(slot_id);
      return next;
    });
    await jpost(`/gates/${gate.gate_id}/undecide`, { slot_ids: [slot_id] });
    if (isCurrentStageContext(actionRound, actionGate)) await load();
    ok(`Undone — ${slot_id} is pending again.`);
  });
  // post-commit reverse ("git for content"): un-reject a dropped item / un-approve -> back to review
  const restore = (slot_id: string) => run(async () => {
    const actionRound = round;
    const actionGate = stage.gate;
    dismissJustApproved(slot_id);   // leaving the just-approved lane back into review
    await jpost(`/slots/${slot_id}/reopen`, {});
    await resumeReviewIfNeeded();
    if (isCurrentStageContext(actionRound, actionGate)) {
      await load();
      await loadDropped();
    }
    await loadRounds();
    await loadPendingApprovals();
    ok(`Restored ${slot_id} — back in review (nothing was lost).`);
  });
  // #14 Phase 1 — safe inline edit of a whitelisted plain-text field (topic hook_text/text_ar). Persists
  // as a NEW head revision server-side (append-only, audited); on success we refresh the active card and
  // any OPEN version-history panel (the #48 discipline) so the edit + its new revision surface at once.
  // On failure we surface the error and DO NOT touch the UI as if it succeeded.
  const editField = (slot_id: string, artifact: "topic" | "script", field: "hook_text" | "text_ar" | "script_ar" | "final_line", value: string) => run(async () => {
    const trimmed = value.trim();
    if (!trimmed) { setToast({ kind: "err", msg: "The edit can’t be empty." }); return; }
    const actionRound = round;
    const actionGate = stage.gate;
    await jpost(`/slots/${slot_id}/edit`, { artifact, field, value: trimmed });
    if (isCurrentStageContext(actionRound, actionGate)) {
      await load();
      if (history.has(slot_id) && reworkStage) {   // refresh an open history panel to show the new revision
        try {
          const rs: Revision[] = await jget(`/slots/${slot_id}/revisions?artifact=${reworkStage}`);
          setRevisions((m) => ({ ...m, [slot_id]: rs }));
        } catch { /* best-effort — a failed history refresh must not fail the save */ }
      }
    }
    await loadRounds();
    ok(`Saved your edit to ${slot_id}.`);
  });
  const submitChange = (slot_id: string) => {
    if (!supportsRework) { setToast({ kind: "err", msg: "Change requests are not enabled for this stage." }); return; }
    const note = (changing[slot_id] || "").trim();
    if (!note) { setToast({ kind: "err", msg: "A change request needs a comment." }); return; }
    decide("request_change", [slot_id], note, "immediate");
  };
  // Refine the change note on an item already sent back, WITHOUT an Undo round-trip. Re-issuing
  // request_change on the still-open gate updates the reviewer note in place (gate_decision INSERT
  // ... ON CONFLICT DO UPDATE); the slot stays CHANGES_REQUESTED (awaiting regeneration) and the new
  // note becomes the rework directive the next regenerate will apply.
  const editChangeNote = (slot_id: string, note: string) => run(async () => {
    if (!supportsRework) { setToast({ kind: "err", msg: "Change requests are not enabled for this stage." }); return; }
    if (!gate) { setToast({ kind: "err", msg: "No open review for this stage." }); return; }
    const trimmed = note.trim();
    if (!trimmed) { setToast({ kind: "err", msg: "A change request needs a comment." }); return; }
    const actionRound = round;
    const actionGate = stage.gate;
    await jpost(`/gates/${gate.gate_id}/decide`, { decision: "request_change", slot_ids: [slot_id], notes: trimmed });
    setNoteDraft((current) => { const next = { ...current }; delete next[slot_id]; return next; });
    if (isCurrentStageContext(actionRound, actionGate)) await loadChanges();
    ok(`Updated the change note for ${slot_id} — regenerate to apply.`);
  });

  const addAsset = (slot_id: string) => run(async () => {
    const uri = (assetUri[slot_id] || "").trim();
    if (!uri) { setToast({ kind: "err", msg: "Add a media reference (path or URL)." }); return; }
    if (!dam) return;
    const actionRound = round;
    const actionGate = stage.gate;
    await jpost(`/slots/${slot_id}/assets`, { stage: dam.stage, kind: dam.kind, uri });
    setAssetUri((m) => ({ ...m, [slot_id]: "" }));
    if (isCurrentStageContext(actionRound, actionGate)) await load();
    ok(`Media added to ${slot_id} (${dam.kind}).`);
  });

  const dispose = (slot_id: string, review: string, action: string) => run(async () => {
    const actionRound = round;
    const actionGate = stage.gate;
    let reason: string | undefined;
    if (action === "waive") {
      const r = window.prompt("Reason for waiving this review? (audited)");
      if (!r || !r.trim()) { setToast({ kind: "err", msg: "Waiving needs a reason." }); return; }
      reason = r.trim();
    }
    await jpost(`/slots/${slot_id}/review/${review}/dispose`, { action, reason });
    if (isCurrentStageContext(actionRound, actionGate)) await load();
    ok(`${review} review ${action === "escalate" ? "escalated" : "waived"} on ${slot_id}.`);
  });

  // "Submit decisions" = commit the recorded per-item decisions (business lexicon for resolve)
  const resolve = () => run(async () => {
    if (!gate) return;
    const actionRound = round;
    const actionGate = stage.gate;
    setSelectedSlotIds(new Set());
    const res = await jpost(`/gates/${gate.gate_id}/resolve`, {});
    const tally: Record<string, number> = {};
    Object.values(res.outcomes as Record<string, string>).forEach((o) => (tally[o] = (tally[o] || 0) + 1));
    if (isCurrentStageContext(actionRound, actionGate)) {
      await load();
      await loadChanges();
      await loadDropped();
    }
    await loadRounds();
    ok("Decisions submitted — " + Object.entries(tally).map(([k, v]) => `${v} ${g("outcome", k) !== k ? g("outcome", k) : k}`).join(", ") + ".");
  });

  // Same resilience contract as generate(): the AUTHORITATIVE completion signal is the DB (the reworked
  // items leave the awaiting-regeneration lane and return to the review status), NOT the ephemeral /jobs
  // registry. /jobs drives only the progress bar. This is what lets a sent-back item reliably re-enter
  // the actionable review even when GET /jobs 404s / times out / is evicted under load — the previous
  // poll gave up after 12 /jobs failures and left the item stuck in "awaiting regeneration".
  const regenerate = () => run(async () => {
    if (!reworkStage) { setToast({ kind: "err", msg: "Regeneration is not available for this stage." }); return; }
    const genRound = round;
    const genGate = stage.gate;
    const rewStage = reworkStage;
    const preCount = changes.length;   // items in the awaiting-regeneration lane before rework
    const r = await jpost(`/rounds/${genRound}/rework?stage=${rewStage}`, {});
    setGenJob({ done: 0, total: r.started, status: "running", label: "Regenerating" });

    const deadline = Date.now() + 120_000;
    let settled = false;
    let jobFinishedAt: number | null = null;

    const reworkLanded = async (): Promise<boolean> => {
      try {
        const ch = await jget(`/rounds/${genRound}/changes?stage=${rewStage}`);
        return Array.isArray(ch) && ch.length < preCount;   // at least one item left the awaiting lane
      } catch {
        return false;
      }
    };

    const settle = async (kind: "done" | "error", errorMsg?: string) => {
      if (settled) return;
      settled = true;
      setGenJob(null);
      if (isCurrentStageContext(genRound, genGate)) {
        await resumeReviewIfNeeded();   // reworked items re-enter the open review (a resume, so auto-open)
        await load();
        await loadChanges();
        // #48: a regenerated revision must also refresh any OPEN version-history panel — otherwise the
        // panel keeps showing the pre-regeneration revision list (stale). `load()` already refreshes the
        // active card content; this brings the history surface to parity (reworkFrom() does the same).
        await Promise.all([...history].map(async (sid) => {
          try {
            const rs: Revision[] = await jget(`/slots/${sid}/revisions?artifact=${rewStage}`);
            setRevisions((m) => ({ ...m, [sid]: rs }));
          } catch { /* best-effort: a failed history refresh must not fail the regenerate */ }
        }));
      }
      await loadRounds();
      if (kind === "error") {
        setToast({ kind: "err", msg: `Regeneration failed: ${errorMsg}` });
        refreshBurst([0, 2000, 5000]);
        return;
      }
      ok(`Regenerated ${r.started} item(s) from your comments.`);
      refreshBurst();
    };

    const poll = async () => {
      if (settled) return;
      let jobFinished = false;
      try {
        const js = await jget(`/jobs/${r.job_id}`);
        setGenJob({ done: js.done, total: js.total, status: js.status, label: "Regenerating" });
        if (js.status === "error") {
          // #207 — same sanitization as generate(): raw job errors are BACKEND-ONLY diagnostics;
          // the client logs only the non-sensitive job id for correlation
          console.warn(`regeneration job ${r.job_id} failed — see server logs / the job registry for diagnostics`);
          await settle("error", "something went wrong and nothing was changed. You can try again.");
          return;
        }
        jobFinished = js.status !== "running";
      } catch {
        // /jobs unavailable — fall back to the authoritative awaiting-lane check
      }
      if (jobFinished) {
        // #207 — the same shared convergence defect as generate(): a "done" job whose items all
        // failed lands nothing in the awaiting lane. Success needs that positive evidence; a
        // short grace covers read lag, then a truthful, retryable failure.
        if (await reworkLanded()) { await settle("done"); return; }
        if (jobFinishedAt === null) jobFinishedAt = Date.now();
        if (Date.now() - jobFinishedAt > 5_000) {
          await settle("error", "no items were regenerated, so nothing changed. You can try again.");
          return;
        }
      } else if (await reworkLanded()) { await settle("done"); return; }
      if (Date.now() > deadline) {
        settled = true;
        setGenJob(null);
        setToast({ kind: "err", msg: "Regeneration is taking longer than expected — refreshing the stage." });
        refreshBurst([0, 2000, 5000]);
        return;
      }
      setTimeout(poll, 1000);
    };
    setTimeout(poll, 800);
  });

  const loadRevisions = async (slot_id: string) => {
    const rs: Revision[] = await jget(`/slots/${slot_id}/revisions?artifact=${reworkStage}`);
    setRevisions((m) => ({ ...m, [slot_id]: rs }));
  };
  const toggleHistory = (slot_id: string) => setHistory((s) => {
    const n = new Set(s);
    if (n.has(slot_id)) n.delete(slot_id); else { n.add(slot_id); loadRevisions(slot_id).catch(() => {}); }
    return n;
  });
  const toggleScript = (slot_id: string) => setOpenScript((s) => {
    const n = new Set(s); n.has(slot_id) ? n.delete(slot_id) : n.add(slot_id); return n;
  });
  const approveVersion = (slot_id: string, revision: number) => run(async () => {
    if (!gate) { setToast({ kind: "err", msg: "Start the review first." }); return; }
    const actionRound = round;
    const actionGate = stage.gate;
    setSelectedSlotIds((current) => {
      const next = new Set(current);
      next.delete(slot_id);
      return next;
    });
    await jpost(`/gates/${gate.gate_id}/decide`, { decision: "approve", slot_ids: [slot_id], revision });
    const res = await jpost(`/gates/${gate.gate_id}/resolve`, { slot_ids: [slot_id] });
    const outcome = res.outcomes?.[slot_id];
    if (isCurrentStageContext(actionRound, actionGate)) await load();
    await loadRounds();
    await loadPendingApprovals();
    ok(outcome === "approved"
      ? `Approved v${revision} of ${slot_id}.`
      : `Recorded approval for v${revision} of ${slot_id} — waiting for the remaining approver(s).`);
  });
  const reworkFrom = (slot_id: string, revision: number) => run(async () => {
    const comment = (reworkFromDraft[`${slot_id}:${revision}`] || "").trim();
    if (!comment) { setToast({ kind: "err", msg: "Add a comment to rework from this version." }); return; }
    await jpost(`/slots/${slot_id}/rework_from`, { artifact: reworkStage, revision, comment });
    setReworkFromDraft((m) => ({ ...m, [`${slot_id}:${revision}`]: "" }));
    ok(`Reworking ${slot_id} from v${revision} with your comment — a new head will appear shortly.`);
    refreshBurst([1500, 4000, 8000, 15000]);
    setTimeout(() => { loadRevisions(slot_id).catch(() => {}); }, 4000);
  });

  // live disposition summary (per-item decisions tallied; business lexicon).
  // #47 (BUG-001) — AUTHORITATIVE SINGLE SNAPSHOT: every count here derives from ONE stage snapshot —
  // the open gate's `targets` (which ARE the visible cards, `orderedTargets`) partitioned by the
  // outcome each card displays, plus the out-of-gate committed lanes from the SAME `stageState`
  // payload (advanced / awaiting / dropped). This must NOT mix the round-wide `review_pending`
  // (a separate slot.status count on a separate refresh cycle) into the in-review numbers, because
  // an item staged-approved-but-not-yet-committed still counts in `review_pending` while the card
  // already shows "approved" — so `review_pending` over-counts pending vs the visible cards.
  // Invariant (gate open): pending + approved + sentBack + rejected == total, and
  //   visibleCards(=inReview) + advanced + awaiting + dropped == total.
  const disposition = useMemo(() => {
    const t = gate?.targets || [];
    const gateOpen = !!gate;
    // out-of-gate committed lanes (items that have LEFT the open review), from the same snapshot
    const committedApproved = stageState?.advanced ?? 0;
    const committedAwaiting = stageState?.awaiting ?? changes.length;
    const committedDropped = stageState?.dropped ?? dropped.length;
    // partition the VISIBLE cards (gate.targets) by the outcome each one renders
    const stagedApproved = t.filter((x) => stagedOutcome(x, approver) === "approved").length;
    const stagedSentBack = t.filter((x) => stagedOutcome(x, approver) === "changes_requested").length;
    const stagedRejected = t.filter((x) => stagedOutcome(x, approver) === "rejected").length;
    const stagedPending = t.filter((x) => stagedOutcome(x, approver) === "pending").length;
    // in-review population = the visible card set when a gate is open; else the round-wide
    // ready-to-start count (no cards rendered yet). pending = still-undecided VISIBLE cards when
    // open (NOT review_pending, which still counts staged-but-uncommitted decisions as pending).
    const reviewPending = stageState?.review_pending ?? 0;
    const inReview = gateOpen ? t.length : reviewPending;
    const pending = gateOpen ? stagedPending : reviewPending;
    return {
      total: inReview + committedApproved + committedAwaiting + committedDropped,
      inReview,
      approved: committedApproved + stagedApproved,
      sentBack: committedAwaiting + stagedSentBack,
      rejected: committedDropped + stagedRejected,
      pending,
      awaiting: committedAwaiting,
      dropped: committedDropped,
      committedApproved,
      committedAwaiting,
      committedDropped,
      stagedApproved,
      stagedSentBack,
      stagedRejected,
      stagedPending,
    };
  }, [gate, stageState, changes.length, dropped.length, approver]);

  const pending = useMemo(
    () => (gate?.targets || []).filter((t) => t.current_outcome === "pending"
      && !t.decisions.some((d) => d.approver_id === approver)),
    [gate, approver],
  );

  // Card ordering: still-actionable items (pending for this reviewer) stay surfaced first;
  // items that already carry a staged/committed disposition sink below — resolved history stays
  // visible, just out of the reviewer's way. Same stagedOutcome() the disposition bar uses, so the
  // card order and the bar counts can never disagree. Explicit index tiebreaker keeps gate order
  // stable within each group. (issue #3 review-surface ordering)
  const orderedTargets = useMemo(() => {
    const t = gate?.targets || [];
    const rank = (x: Target) => (stagedOutcome(x, approver) === "pending" ? 0 : 1);
    return t
      .map((target, index) => ({ target, index }))
      .sort((a, b) => rank(a.target) - rank(b.target) || a.index - b.index)
      .map((entry) => entry.target);
  }, [gate, approver]);

  useEffect(() => {
    const allowed = new Set(pending.map((target) => target.slot_id));
    setSelectedSlotIds((current) => {
      const next = new Set(Array.from(current).filter((slotId) => allowed.has(slotId)));
      return next.size === current.size ? current : next;
    });
  }, [pending]);

  const toggleSelected = (slot_id: string) => setSelectedSlotIds((current) => {
    const next = new Set(current);
    if (next.has(slot_id)) next.delete(slot_id);
    else next.add(slot_id);
    return next;
  });
  const clearSelected = () => setSelectedSlotIds(new Set());
  const selectAllPending = () => setSelectedSlotIds(new Set(pending.map((target) => target.slot_id)));
  const selectedPending = useMemo(
    () => pending.filter((target) => selectedSlotIds.has(target.slot_id)),
    [pending, selectedSlotIds],
  );

  // #215 — on an actual persona TRANSITION, the previous persona's authority projection must not
  // survive under the new badge even for a moment. Bumping the loader sequences discards any late
  // prior-persona success (last-STARTED wins); clearing the state makes the UI fail CLOSED and
  // truthful while the new persona loads — and, critically, if the new persona's authority request
  // rejects or never resolves, no stale approvals/admin capability can linger. Authority-derived
  // state ONLY (pending approvals, roles/groups, admin capability, policies) — never round/view
  // display state. Bound to the transition, so same-persona refreshes never flicker.
  const invalidatePersonaAuthority = () => {
    pendingApprovalsSeq.current++;
    approvalCatalogSeq.current++;
    setPendingApprovals([]);
    setPrincipalRoles([]);
    setPrincipalGroups([]);
    setApprovalAdmin(false);
    setApprovalPolicies({});
  };

  const syncApprover = (value: string) => {
    if (!value || value === approver) return;
    setReviewerSyncing(true);
    invalidatePersonaAuthority();     // fail closed immediately; the switch below reloads under the new persona
    fetch("/api/reviewer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer: value }),
    }).then(() => {
      // #170 — the inline switcher also pins THIS window's persona, so switching here never
      // silently re-identifies other open windows (the cookie stays the browser-wide default).
      setSessionPersona(value);
      setApprover(value);
      loadPendingApprovals().catch(() => {});
      loadApprovalCatalog().catch(() => {});
      load().catch(() => {});
    }).catch(() => {
      setToast({ kind: "err", msg: "Reviewer switch failed. Try again." });
    }).finally(() => {
      setReviewerSyncing(false);
    });
  };

  // #170 — demo persona entry: pin the persona for THIS window first (the header override is what
  // the /gw proxy signs), then best-effort persist the browser-wide cookie default and refresh the
  // persona-dependent surfaces. Selection is from known principals only — never free text — and is
  // operational identity, not authentication: the gate API still authorizes at decide time (#10).
  const enterPersona = (value: string) => {
    if (!value) return;
    // #215 — entering/transitioning to a persona clears any prior authority projection first, so
    // the pre-pick default persona's approvals/admin can never show under the picked badge (even
    // if the picked persona's authority load is slow or fails).
    if (value !== approver) invalidatePersonaAuthority();
    setSessionPersona(value);
    setApprover(value);
    setPersonaEntry(false);
    fetch("/api/reviewer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reviewer: value }),
    }).catch(() => { /* cookie is a convenience default; the window header is already active */ });
    loadPendingApprovals().catch(() => {});
    loadApprovalCatalog().catch(() => {});
    load().catch(() => {});
  };

  return {
    view, setView, roundStates, loadStates, genMode,
    rounds, roundsLoading, roundsError, reloadRounds: loadRounds, round, setRound, roundInfo, stageKey, setStageKey, stage, isTopic, dam, supportsRework, reworkStage,
    gate, changes, dropped, justApproved, dismissJustApproved, stageState, approver, approvers, principalRoles, principalGroups, pendingApprovals,
    approvalAdmin, approvalPolicies, savingPolicyStage, reviewerSyncing, setApprover: syncApprover, saveApprovalPolicy,
    personaEntry, enterPersona, canDecideGate, gateRequirements, advancedTrail, iam,
    publications, platforms, recordPublication, completePublication, inspectSlot, sdamState, sdamHandoff, sdamRegisterEdit,
    toast, setToast, busy, g, pending, orderedTargets, disposition, selectedSlotIds, selectedPending, toggleSelected, clearSelected, selectAllPending,
    changing, setChanging, noteDraft, setNoteDraft, openScript, toggleScript, history, toggleHistory, revisions,
    reworkFromDraft, setReworkFromDraft, assetUri, setAssetUri,
    openGate, decide, submitChange, editChangeNote, editField, undecide, restore, addAsset, dispose, resolve, regenerate,
    approveVersion, reworkFrom, refresh,
    plan, getBaselineEligibility, generate, genJob, frameworks,
    roundSlots, reviseSchedule, roundPinned, roundMix, reviseRunMix,
  };
}

type ReviewCtx = ReturnType<typeof useReviewState>;
const Ctx = createContext<ReviewCtx | null>(null);
export function ReviewProvider({ children }: { children: React.ReactNode }) {
  return <Ctx.Provider value={useReviewState()}>{children}</Ctx.Provider>;
}
export function useReview() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useReview must be used within ReviewProvider");
  return c;
}
