// #293 Stage 0 — typed shapes for the read model V2 consumes.
//
// These types MIRROR the Tanaghom read model; they do not define it. Tanaghom is the sole
// authority. Fields V2 does not need are simply absent here — absence is not a claim that the
// server lacks them, and V2 must never re-derive, default, or "complete" server truth locally.
//
// Deliberately NOT modelled at Stage 0:
//   - human-facing display order / display codes. V1 derives these client-side today
//     (dashboard/lib/content-id.ts); #292 (Stage 1) owns the *persisted, versioned, audited*
//     mapping. V2 therefore renders the canonical slot_id only. Inventing a display code here
//     would silently pre-empt #292's contract and create exactly the frontend-local shadow model
//     #293 forbids.

/** Row of GET /rounds — the round list read model. */
export type RoundSummary = {
  round_id: string;
  label?: string | null;
  phase?: string | null;
  slots?: number;
  /** #304 — the run's ONLY authoritative absolute placement (ISO date), server-owned.
   *
   *  `null`/absent means the run was never governed-placed (legacy, or created through V1's
   *  placement-less form) and MUST render as explicitly UNPLACED. It is never substituted with
   *  `created_at`, never defaulted to today, never inferred: an invented start would be
   *  indistinguishable from a governed one. Window = [starts_on, starts_on + period_len_days);
   *  a slot's absolute datetime = starts_on + (day-1) at its time_uae. V2 projects that; it does
   *  not own it. */
  starts_on?: string | null;
  period_len_days?: number;
  posts_per_day?: number;
};

/** A slot as returned inside GET /rounds/{id}. `slot_id` is the canonical, immutable identity. */
export type SlotDetail = {
  slot_id: string;
  day?: number;
  time_uae?: string | null;
  status?: string | null;
  pillar_code?: string | null;
  hcs_id?: string | null;
  format?: string | null;
};

/** GET /rounds/{id} — the run read model (#271). */
export type RoundDetail = {
  round_id: string;
  label?: string | null;
  status?: string | null;
  posts_per_day?: number;
  period_len_days?: number;
  /** #304/#308 — the run's authoritative absolute start (ISO date). `null`/absent = unplaced; the
   *  selected-run views then show an explicit unplaced state and never fabricate a date. The server
   *  (`round_detail`) already returns this; V2 projects slots over `[starts_on, starts_on +
   *  period_len_days)` — a slot's datetime is `starts_on + (day-1)` at its `time_uae`. */
  starts_on?: string | null;
  planned_total?: number;
  slots: SlotDetail[];
  status_counts?: Record<string, number>;
};

/** #310 §F — one durable Topic-generation JOB as the server reports it. Phase/counts/typed error
 *  are server truth; V2 renders them verbatim and never infers a phase client-side. */
export type GenerationJob = {
  job_id: string;
  accepted_schedule_token?: number | null;
  stage?: string | null;
  status: string;                     // queued | running | partial | failed | completed
  slots_total?: number;
  slots_done?: number;
  slots_failed?: number;
  trigger_source?: string | null;
  error_detail?: unknown;             // typed error object or null — shown as-is, never invented
  entry_mode?: "automatic" | "manual" | null;   // #310 — pinned resolved mode this job ran under
  created_at?: string | null;
  updated_at?: string | null;
};

/** #310 §F — the resolved provenance DISCLOSURE for a generated Topic. Resolved truth (what ran),
 *  never configured intent. Absent fields are simply not disclosed — never defaulted. */
export type TopicProvenanceDisclosure = {
  resolved_provider?: string | null;
  resolved_model?: string | null;
  execution_route?: string | null;
  novelty_brief_version?: string | null;
  methodology_version?: string | null;
  topic_generation_policy_id?: string | null;
  accepted_schedule_token?: number | null;
};

/** #310 §F — one accepted slot's Topic-generation result. `topic`/`provenance` are null until the
 *  slot is populated; canonical `topic_id` + append-only `revision` are the Topic identity. */
export type GenerationResult = {
  slot_id: string;
  accepted: { pillar_code?: string | null; hcs_id?: string | null; format?: string | null };
  slot_status?: string | null;
  topic: null | { topic_id: string; revision: number; title?: string | null; meaning?: string | null };
  provenance: null | TopicProvenanceDisclosure;
};

/** GET /rounds/{id}/generation — the Stage 2A read model (#310 §F). `stage2a_enabled=false` means
 *  Stage 2A is not provisioned for the run (no generation command available): an empty, non-erroring
 *  model. `phase` is server-derived from the latest job (empty | queued | running | partial | failed |
 *  completed) — V2 reports it, never infers it. */
export type TopicGenerationReadModel = {
  round_id: string;
  stage2a_enabled: boolean;
  /** #310 — governed Schedule-to-Topic entry mode for this round's scope: 'automatic' auto-generates
   *  after Schedule acceptance; 'manual' is a V2-governed authorized trigger-timing choice over the
   *  SAME durable job; null = Stage 2A not provisioned. Server-resolved from the versioned policy; V2
   *  reports it, never infers it. */
  entry_mode: "automatic" | "manual" | null;
  phase: string;
  jobs: GenerationJob[];
  results: GenerationResult[];
  counts: { accepted: number; generated: number };
};

/** #313 — one immutable revision in a Topic's append-only chain (mirrors engine.list_revisions). */
export type TopicRevision = {
  revision: number;
  topic_id?: string | null;           // the IMMUTABLE id of THIS revision row (per-revision, NOT stable across revisions)
  hook_text?: string | null;
  body?: string | null;               // text_ar (topic source language) / script excerpt
  feedback?: string | null;
  change_summary_ar?: string | null;
  change_summary_en?: string | null;
  base_revision?: number | null;      // the parent/restored-from revision this one derives from
  created_at?: string | null;
  approved?: boolean;                 // is this the pinned approved revision
};

/** #313 — the explicit identity disclosure. slot_id is the stable per-item key; topic_id is per-revision
 *  (see revisions[].topic_id) and is NOT a stable cross-revision id. Rendered truthfully; never conflated. */
export type TopicIdentity = {
  stable_key: string;                 // "slot_id"
  slot_id: string;
  head_topic_id?: string | null;
  topic_id_scope: string;             // "per_revision"
  note?: string;
};

/** #313 — a typed available/denied action. `reason` is the server's machine reason on denial
 *  (approved | downstream_advanced | already_approved | not_in_review); V2 renders it, never derives it. */
export type TopicItemAction = { allowed: boolean; reason?: string };

/** GET /slots/{id}/topic_item — the #313 canonical per-item Topic read model. Server-owned durable
 *  truth: stable slot_id, current status, head/approved revision pointers, the immutable append-only
 *  revision history, and the typed action map. V2 renders it verbatim and offers only the actions the
 *  server marks allowed — it never infers eligibility client-side. */
export type TopicItemReadModel = {
  slot_id: string;
  artifact: string;
  status?: string | null;
  head_revision: number;
  approved_revision?: number | null;
  downstream_advanced?: boolean;
  identity?: TopicIdentity;
  // #373 (Codex ruling 2) — the EXACT authoritative gate id `undecide` is addressed to, projected by
  // the server ONLY when exactly one open gate applies (else null -> the surface renders the typed
  // `undecide` unavailable state). The client consumes this id DIRECTLY: it never derives, sorts,
  // searches, falls back, or chooses among gates. Additive + optional; V2-only (V1 never reads this).
  authoritative_gate_id?: string | null;
  revisions: TopicRevision[];
  // #373 — `actions` additionally carries `reopen` (reverse a committed decision — DISTINCT from
  // `restore`=restore_revision) and `undecide` (pre-commit clear), each typed {allowed, reason}.
  actions: Record<string, TopicItemAction>;
};

/** A governed WRITE refusal — carries the server's typed reason so the UI states WHY (a stale-revision
 *  race, or a governed denial that leaves #249 unconsumed), never a generic failure. V2 relays; it
 *  invents no authority and reinterprets nothing. */
export class WriteError extends Error {
  readonly status: number;
  readonly error?: string;      // "stale_revision" | "governed_denial" | ...
  readonly reason?: string;     // governed_denial: approved | downstream_advanced | already_approved
  readonly current?: number;    // stale_revision: the current head to refresh to
  readonly code?: string;       // #377/#376 typed authority code, e.g. "recommendation_stale"
  readonly detail?: unknown;    // the full typed detail object, surfaced as-is (never invented)
  constructor(status: number, body: { error?: string; reason?: string; current?: number; detail?: string; code?: string }) {
    super(body?.detail || body?.error || `${status}`);
    this.name = "WriteError";
    this.status = status;
    this.error = body?.error;
    this.reason = body?.reason;
    this.current = body?.current;
    this.code = body?.code;
    this.detail = body;
  }
}

/** POST a governed write through V2's own allowlisted seam. A typed upstream refusal (409
 *  stale_revision / governed_denial) is surfaced as WriteError so the UI relays the exact reason. No
 *  retries, no fabricated success. */
export async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body), signal, cache: "no-store",
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new WriteError(0, { detail: "network unreachable" });
  }
  const text = await res.text();
  let parsed: Record<string, unknown> = {};
  try { parsed = text ? (JSON.parse(text) as Record<string, unknown>) : {}; }
  catch { parsed = { detail: text.slice(0, 200) }; }
  if (!res.ok) {
    // FastAPI wraps our typed dict under `detail`; unwrap so error/reason/current surface.
    const d = (parsed.detail && typeof parsed.detail === "object" ? parsed.detail : parsed) as {
      error?: string; reason?: string; current?: number; detail?: string; code?: string;
    };
    throw new WriteError(res.status, d);
  }
  return parsed as T;
}

/** #331 — one baseline-eligible framework for the governed New-run form (mirrors
 *  engine.resolve_run_eligibility `eligible[]`). `name` is what the planner's `format_mix` contract
 *  validates against; the ids are diagnostic. V2 renders these and sums a proposed mix, but the planner
 *  owns validation — a bad mix is relayed as the server's typed 422, never pre-judged here. */
export type EligibleFramework = {
  name: string;
  format_key?: string | null;
  version_id?: string | null;
  framework_id?: string | null;
};

/** GET /baseline-eligibility — the current baseline policy + its eligible frameworks (#276/#271). */
export type BaselineEligibility = {
  policy?: Record<string, unknown>;
  eligible: EligibleFramework[];
};

/** GET /health on the gate API — the writer/runtime read model V2 reports verbatim. */
export type ApiHealth = {
  ok: boolean;
  writer_mode?: string;
  dev_mode?: boolean;
};

export type RuntimeIdentity = {
  surface: string;
  build: string;
  lane?: string;
  identity?: string;
  /** #342 — the NAMED lane instance (e.g. "acc342"); "unknown" for an ordinary process. */
  lane_id?: string;
  /** #342 — whether this process is serving declared synthetic fixtures. Never defaults to
   *  "synthetic": an undeclared process is "unknown", so the banner can never reassure falsely. */
  data_class?: "synthetic" | "unknown";
};

/** A read that failed. Carries the upstream status so the UI can be truthful about WHY, rather
 *  than collapsing every failure into a generic "something went wrong". */
export class ReadError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ReadError";
    this.status = status;
  }
}

/** GET a JSON read through V2's own allowlisted seam. Never throws a bare network error: a
 *  transport failure and a typed upstream error are both surfaced as ReadError so the UI can show
 *  the real reason. No retries, no fallbacks, no fabricated empty success. */
export async function readJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { signal, cache: "no-store" });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ReadError(0, "network unreachable");
  }
  const text = await res.text();
  if (!res.ok) {
    // Preserve the server's typed error text when it sent one.
    let detail = `${res.status}`;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed?.detail) detail = parsed.detail;
    } catch {
      if (text) detail = text.slice(0, 200);
    }
    throw new ReadError(res.status, detail);
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ReadError(res.status, "malformed response from the read path");
  }
}

// ---------------------------------------------------------------------------
// #355 — the governed workflow version + the Scripts read model.

/** One stage row of the active governed workflow version (mirrors engine._workflow_stage_read_model).
 *  This is the ONLY source of V2's stage rail — see lib/stage-rail.ts. */
export type WorkflowStage = {
  stage_key: string;
  stage_label: string;
  stage_group: string;
  ordinal: number;
  enabled: boolean;
  gate_stage: string;
  stage_kind: string;
  generator_kind: string | null;
  writer_mode: string | null;
  generates_from: string | null;
  approve_to: string | null;
};

/** The active governed configuration generation. `version_no`/`status` are rendered as provenance so
 *  a reader can tell WHICH generation produced the rail they are looking at. */
export type WorkflowVersion = {
  version_id: string;
  version_no: number;
  status: string;
  stages: WorkflowStage[];
};

/** Generic per-stage lifecycle state (gates/api.py:1453). Deliberately loose: V2 renders what the
 *  server sent and interprets none of it. */
export type StageState = {
  stage?: string;
  status?: string;
  counts?: Record<string, number>;
  [k: string]: unknown;
};

/** One immutable revision of a slot's SCRIPT artifact (engine.list_revisions, artifact="script").
 *  `body` is upstream's own truncation (left(script_ar,200)) — V2 truncates nothing further and
 *  fabricates nothing. */
export type ScriptRevision = {
  revision: number;
  final_line: string | null;
  body: string | null;
  feedback: string | null;
  change_summary_ar: string | null;
  change_summary_en: string | null;
  base_revision: number | null;
  model: string | null;
  needs_scholar_review: boolean | null;
  needs_native_review: boolean | null;
  created_at: string | null;
  approved: boolean;
};

/** #357 — the SERVER-OWNED typed action decision for Script generation.
 *  V2 projects this and recomputes nothing: availability, the denial reason, the attempt identity and
 *  the pinned inputs are all decided upstream. A surface that re-derived eligibility could disagree
 *  with the authority that actually governs the command. */
export type ScriptActionDecision = {
  action: "script_generate";
  round_id: string;
  stage: string;
  available: boolean;
  reason_code: string | null;
  detail?: string;
  attempt_id: string | null;
  job_status?: string | null;
  manifest_digest: string | null;
  manifest_version?: string;
  input_revisions?: { slot_id: string; topic_id: string; topic_revision: number }[];
  source_gate_id?: string | null;
  source_decision_generation?: string | null;
  workflow_version_id?: string | null;
  subject_principal?: string | null;
  capability_binding?: string | null;
  requires_confirmation?: boolean;
  retry_safe?: boolean;
};

/** #419 — the read-only Stage 4 approval-package preflight (GET /slots/{id}/stage4_preflight).
 *  Server-authoritative: the surface renders `available` + `reason_code`/`denials` + `evidence`
 *  VERBATIM and reconstructs nothing. Consumed and active workflow identity are DISTINCT facts; a
 *  divergence, or any missing/underivable pin, is a fail-closed typed denial — never eligible by
 *  implication. `detail` is display-only and must not be parsed into readiness or lineage. */
export type Stage4WorkflowIdentity =
  | { version_id: string; version_no?: number; status?: string; source?: string }
  | { status: "unknown" | "unavailable" };

export type Stage4Denial = { code: string; detail: string };

export type Stage4Preflight = {
  candidate: { slot_id: string };
  available: boolean;
  reason_code: string;
  detail: string;
  evidence: {
    schedule: { slot_id: string; round_id: string; status: string } | null;
    topic: { topic_id: string; revision: number } | null;
    script: { script_id: string; revision: number } | null;
    workflow: {
      consumed: Stage4WorkflowIdentity | null;
      active: Stage4WorkflowIdentity | null;
      divergent: boolean | null;
    };
    consumed_versions: {
      methodology_version: string | null;
      content_format_version: string | null;
      framework_version: string | null;
      writer_contract_version: string | null;
    } | null;
    final_review:
      | {
          required: true;
          human_required: boolean;
          source_version_id: string;
          approval_rule: string;
          enforce_mandatory_reviews: boolean;
          mandatory: boolean;
          approve_to: string | null;
        }
      | { status: "unknown" }
      | null;
    // #419 amendment: absence before human final review is the non-blocking `not_yet_recorded` status;
    // a persisted direction that is `malformed` (fails the canonical package contract) or `mismatch`
    // (references a different script/revision/slot) is a fail-closed denial (see `denials`).
    production_direction: {
      present: boolean;
      status?: "not_yet_recorded" | "malformed" | "mismatch";
      directive_id?: string;
      revision?: number;
      expected_revision?: number | null;
    };
    classifications: {
      agent_execution: string;
      agent_rep_delegation: string;
      provider_operation: string;
      secret_authority: string;
    };
  };
  denials: Stage4Denial[];
};

/** #423 — read-only immutable final-review target-package evidence for one (gate, slot)
 *  (GET /gates/{gate_id}/slots/{slot_id}/target-package). The SOLE typed disclosure surface for
 *  recorded-vs-`unknown_history`; the projection renders it VERBATIM and reconstructs nothing. A
 *  legacy target (attached before migration 036) is `unknown_history`; a non-target pair is
 *  `unavailable`; neither is an error, and neither is ever an authorization result. */
export type TargetPackageEvidence = {
  gate_id: string;
  slot_id: string;
  recorded: boolean;
  status: "recorded" | "unknown_history" | "unavailable";
  evidence: {
    snapshot_id: string;
    round_id: string;
    topic_id: string;
    topic_revision: number;
    script_id: string;
    script_revision: number;
    workflow_version_id: string;
    workflow_version_source: "script_provenance" | "round_policy_snapshot";
    production_direction: { present: boolean; directive_id?: string; revision?: number };
    attached_at: string | null;
  } | null;
};

/** #427/#429 — the authoritative Stage-4 final-review READ projection for one admitted (gate, slot)
 *  (GET /gates/{gate_id}/slots/{slot_id}/final-review-projection). The backend is the SOLE authority
 *  for aggregation, evidence status, historical uncertainty, decision attribution, and audit scope;
 *  V2 renders these typed groups VERBATIM and reconstructs/joins/infers nothing. Each evidence group
 *  carries its OWN status and may be absent (`null`) or typed-uncertain INDEPENDENTLY of the others.
 *  Frozen eligible principals are HISTORY, never present authority; audit is gate-scoped and never
 *  slot-attributable; the surface withholds raw principal IDs from identity presentation. Types mirror
 *  the endpoint SHAPES only — no frontend-owned workflow semantics or synthesized defaults; a group's
 *  typed distinction is never weakened into a fallback/truthiness collapse. */
export type FinalReviewStatus = "recorded" | "unknown_history" | "unavailable";

/** One frozen required token + its historically eligible principals (raw IDs, withheld from display). */
export type FinalReviewToken = {
  token_kind: string;
  token_key: string;
  normalized_token: string;
  eligible_principals: string[];
};

export type FinalReviewProjection = {
  gate_id: string;
  slot_id: string;
  /** true iff top-level `status === "recorded"` — the canonical SLOT evidence only, never audit. */
  available: boolean;
  status: FinalReviewStatus;
  target_identity: {
    gate_id: string;
    slot_id: string;
    gate_stage: string;
    gate_status: string;
    admitted: boolean;
  } | null;
  /** Immutable attached package evidence (#423 shape), reused verbatim. `null`/typed on early unavailable. */
  package: TargetPackageEvidence | null;
  /** GATE-WIDE frozen assignment snapshot (never target-level). `null` when no governing snapshot. */
  assignment: {
    recorded: boolean;
    status: "recorded";
    snapshot_id: string;
    snapshot_version: number | null;
    opened_at: string | null;
    rule_key: string;
    tokens: FinalReviewToken[];
  } | null;
  /** Persisted decision + head-correct coverage evidence — evidence values, never action opportunities.
   *  Fails closed to a non-`recorded` status on ambiguous attribution. `null` when no governing snapshot. */
  decision_evidence: {
    recorded: boolean;
    status: "recorded" | "unknown_history";
    reasons: string[];
    governing_snapshot_id: string;
    outcome: string;
    approval_count: number;
    distinct_principal_coverage: number;
    coverage: {
      token_kind: string;
      token_key: string;
      normalized_token: string;
      covered_by: string | null;
    }[];
    decisions: {
      approver_id: string;
      decision: string;
      revision: number | null;
      decided_at: string | null;
    }[];
  } | null;
  /** GATE-SCOPED audit history ONLY — `slot_attributable` is always false; never `recorded`. */
  audit_evidence: {
    scope: "gate";
    slot_attributable: false;
    status: "gate_scoped_history" | "unavailable";
    reasons: string[];
    events: {
      id: number;
      action: string;
      actor: string | null;
      at: string | null;
    }[];
  } | null;
  uncertainty: string[];
};

/** #447 — the read-only Stage 4 approval-package preflight for one admitted (gate, slot)
 *  (GET /gates/{gate_id}/slots/{slot_id}/approval-preflight). The read-only GET counterpart of the
 *  #439 sign-off command: it reports whether the IMMUTABLE pinned package is still fully pinned,
 *  still governed by the current generation, and still presently eligible for a human final-review
 *  sign-off. The backend is the SOLE authority; V2 renders these typed fields VERBATIM and performs
 *  no join, no coverage math, no lineage reconstruction, and no reason-code reinterpretation.
 *
 *  Invariants this type deliberately encodes:
 *    • `target_package_tuple` is ALL SIX members or `null` — a partially pinned package is never
 *      returned, so the client can never assemble one from a partial object;
 *    • authority is STRUCTURAL only (`authorization_evaluated` is always false). This response never
 *      states that any principal may act, and the surface must never present it as permission;
 *    • `available` is an eligibility VERDICT; `status` is the HISTORICAL evidence status. They are
 *      distinct facts and are never collapsed into one another;
 *    • `denials` arrive PRE-SORTED in the server's documented precedence order and `reason_code` is
 *      its head — the client never re-ranks, re-sorts, or re-derives the primary reason;
 *    • the production direction is downstream EVIDENCE only — never approval, sign-off, lifecycle
 *      advancement, or authorization to execute Production. */
export type ApprovalPreflightDenial = { code: string; detail: string };

/** The six unconditional immutable-package members. All present, or the whole object is `null`. */
export type ApprovalPreflightTuple = {
  gate_id: string;
  slot_id: string;
  snapshot_id: string;
  topic_revision: number;
  script_revision: number;
  workflow_version_id: string;
};

export type ApprovalPreflight = {
  gate_id: string;
  slot_id: string;
  /** Eligibility verdict: true only when NOTHING failed. Never inferred from `status`. */
  available: boolean;
  /** Historical evidence status — a separate fact from `available`. */
  status: FinalReviewStatus;
  /** Deterministic primary reason, or `"coherent"`. The head of `denials`; never re-derived. */
  reason_code: string;
  /** Display-only. Must never be parsed into lineage, readiness, or authority. */
  detail: string;
  target_identity: {
    gate_id: string;
    slot_id: string;
    gate_stage: string;
    gate_status: string;
    admitted: boolean;
  } | null;
  /** The immutable #423 evidence, reused verbatim. */
  package: TargetPackageEvidence | null;
  target_package_tuple: ApprovalPreflightTuple | null;
  evidence: {
    /** Pinned is EVIDENCE; active is a COHERENCE CHECK. Divergence is a server-side denial. */
    workflow: {
      pinned: { version_id: string; source: string } | null;
      active:
        | { version_id: string; version_no?: number; status?: string }
        | { status: "unavailable" }
        | null;
      divergent: boolean | null;
    };
    /** STRUCTURAL hard-floor evidence only — never a statement about any principal. */
    final_review: {
      stage: string;
      actor_model_enabled: boolean;
      hard_floor_stage: boolean;
      human_signoff_required: boolean;
      source: string;
      authorization_evaluated: false;
    } | null;
    /** Actor-independent present-state facts. Carries no principal identity of any kind. */
    present_state: {
      gate_status: string;
      outcome: string | null;
      governed_head: { topic: number | null; script: number | null };
    } | null;
    production_direction: {
      pinned: { present: boolean; directive_id?: string; revision?: number };
      observed: { present: boolean; directive_id?: string; revision?: number };
      status: "recorded" | "mismatch" | "not_yet_recorded";
    } | null;
    classifications: {
      agent_execution: string;
      agent_rep_delegation: string;
      provider_operation: string;
      secret_authority: string;
    };
  };
  denials: ApprovalPreflightDenial[];
};

/** #449 — the EXACT sign-off request body (mirrors `SignOffBody`, which is `extra="forbid"`).
 *
 *  Five fields, and structurally no more: the four immutable-package binding fields, forwarded
 *  VERBATIM from the server-authored #448 preflight tuple, plus an opaque client idempotency key used
 *  SOLELY for request deduplication. There is deliberately no actor, principal, role, authority,
 *  package, generation, or eligibility field — the signed principal is resolved server-side by the /gw
 *  route and authorized by the gate API, and any extra field is a typed 422 at parse time. */
export type SignOffRequest = {
  snapshot_id: string;
  topic_revision: number;
  script_revision: number;
  workflow_version_id: string;
  /** Opaque, random, and carrying NO authority meaning. Deduplication only (#449 Q3). */
  idempotency_key: string;
};

/** #449 — the sign-off receipt (mirrors `engine._signoff_receipt`), returned on a recorded sign-off
 *  AND on an identical idempotent replay. It is server-authored evidence that a receipt exists; V2
 *  renders it verbatim and derives no lifecycle transition, approval, or authority from it. */
export type SignOffReceipt = {
  signoff_id: string;
  operation: string;
  /** Pinned to the contract literal. `engine._signoff_receipt` emits `'recorded'` on BOTH the
   *  recording path and the idempotent replay — there is no other value in the canonical shape, and
   *  `classifySuccess` refuses anything else as contract drift rather than rendering it. */
  status: "recorded";
  gate_id: string;
  slot_id: string;
  snapshot_id: string;
  topic_revision: number;
  script_revision: number;
  workflow_version_id: string;
  recorded_at: string;
};

// ---------------------------------------------------------------------------
// R1 Stage 4 — the two canonical reads the Final Review workspace consumes.

/** The Final Review stage's lifecycle state (`engine.stage_state`).
 *
 *  Every field here is SERVER-AUTHORED and rendered as-is. `gate_id` is the canonical identity of the
 *  stage's ACTIVE open gate as the server resolved it (orphan/duplicate gates already excluded
 *  upstream) — the client consumes it directly and never searches, sorts, or chooses among gates. A
 *  null `gate_id` means the server reports no active gate, which is a truthful state, not an error.
 *
 *  `state` is the governed lifecycle word (`reviewing`, `ready_to_commit`, `complete`, `empty`, …).
 *  V2 renders it and derives nothing from it: it is not re-mapped, ranked, or used to conclude what
 *  may happen next beyond withholding controls the server's own evidence does not support. */
export type FinalReviewStageState = {
  round_id?: string;
  stage?: string;
  gate_id?: string | null;
  state?: string;
  next_action?: string;
  in_review?: number;
  approved?: number;
  sent_back?: number;
  rejected?: number;
  pending?: number;
  advanced?: number;
  awaiting?: number;
  dropped?: number;
  recommendation?: string;
  /** Advisory ONLY (agents recommend; the human commits). Rendered verbatim, never acted on. */
  warnings?: string[];
  confirm_warnings?: string[];
  reconciliation_ok?: boolean;
  approval_rule?: string;
  approval_quorum?: number;
  [k: string]: unknown;
};

/** One server-authored target of a canonical gate (`engine.get_gate` -> `targets[]`).
 *
 *  `current_outcome` is the SERVER's rollup of the decisions recorded on this gate for this slot. V2
 *  never recomputes it from decisions, never infers it from slot status, and treats an unrecognized
 *  value as "not decided" rather than guessing (see lib/final-review-advancement.ts). The read model is
 *  deliberately loose beyond the members this surface uses — the gate detail carries the full review
 *  payload and V2 must not imply it consumes more of it than it does. */
export type GateTarget = {
  slot_id: string;
  current_outcome?: string;
  slot_status?: string;
  topic_revision?: number | null;
  script_revision?: number | null;
  [k: string]: unknown;
};

/** The canonical gate detail (`engine.get_gate`). The ONLY truthful source of which slots this gate
 *  governs — deriving that set from round slots or slot status would be the client-side eligibility
 *  determination this lane forbids. */
export type GateDetail = {
  gate_id: string;
  stage?: string;
  status?: string;
  quorum?: number;
  targets?: GateTarget[];
  [k: string]: unknown;
};
