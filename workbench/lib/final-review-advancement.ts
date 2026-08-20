// R1 Stage 4 — pure, JSX-free logic for the V2 final-review ADVANCEMENT actions.
//
// THE ONE DISTINCTION THIS MODULE EXISTS TO HOLD. Stage 4 has three facts that are routinely
// conflated, and conflating them is the specific failure this lane must not ship:
//
//   1. EVIDENCE CREATION   — `sign_off` records an immutable, attributable, exact-target-bound human
//                            receipt (#439/#440). It grants no authority and moves no lifecycle.
//   2. AUTHORITY DECISION  — `POST /gates/{gate}/decide` records a governed approve / reject /
//                            request_change through the canonical gate authority (quorum, assignment,
//                            frozen eligibility, audit). Still not a lifecycle transition.
//   3. LIFECYCLE TRANSITION— `POST /gates/{gate}/resolve` applies the quorum and moves each slot to the
//                            stage's governed `approve_to` (or loops it back). This is the transition.
//
// This module owns (2) and (3) ONLY. It imports nothing from the sign-off module and exports nothing
// the sign-off surface consumes: there is no code path here by which recording evidence can cause a
// decision or a transition. `lib/sign-off-action.ts` is the mirror image — it cannot advance anything.
// That separation is the invariant, enforced by construction rather than by a comment.
//
// CURRENT ADVANCEMENT MODE IS MANUAL, AND THAT IS WORKFLOW BEHAVIOUR, NOT A PLATFORM INVARIANT.
// The operator invokes (2) and then (3) explicitly, as two distinct gestures. Nothing here schedules,
// chains, debounces, or implies the next step, and no result of one is a trigger for another.
//
// HOW A FUTURE GOVERNED AUTOMATIC-ADVANCEMENT POLICY STAYS POSSIBLE WITHOUT REDESIGNING AUTHORITY.
// Automatic advancement, if a later workflow/stage policy generation adopts it, must execute ON THE
// SERVER: reload present state, re-evaluate authority, revalidate the exact target/version binding,
// then call the SAME canonical `decide` + `resolve` machinery. Nothing in this module stands in the
// way of that, because this module contains no authority and no policy — it builds two request bodies
// against two canonical endpoints and classifies what comes back. The seam is preserved by SEPARATION
// OF RESPONSIBILITY, deliberately NOT by speculative schema: there is no `advancement_mode` field, no
// `auto_advance` flag, no policy persistence, and no operator toggle, because no such canonical field
// exists today and inventing one would be the redesign this slice is forbidden to make.
//
// The provenance a future automatic mode needs is already distinct and stays distinct: the sign-off
// receipt carries the HUMAN actor and its own timestamp, while decide/resolve are separately audited
// server-side against the principal the /gw route signs. This surface attributes nothing itself, so it
// cannot ever mis-attribute a system-triggered transition to the human who supplied the evidence.

// Type-only import, exactly as lib/sign-off-action.ts does it: this module must carry NO runtime
// dependency on read-model so it stays loadable under `node --experimental-strip-types` (a value
// import would need a `.ts` specifier).
import type { ApprovalPreflightTuple, WriteError } from "./read-model";

/** The EXACT canonical decision vocabulary. MIRRORS `engine.DECISIONS`; it does not define it.
 *
 *  Declared once, here, so a drift in the server vocabulary is caught by the focused test rather than
 *  silently mis-rendered. V2 never invents, renames, merges or re-ranks a decision. */
export const GATE_DECISIONS = ["approve", "reject", "request_change"] as const;

export type GateDecision = (typeof GATE_DECISIONS)[number];

export function isGateDecision(value: unknown): value is GateDecision {
  return typeof value === "string" && (GATE_DECISIONS as readonly string[]).includes(value);
}

// --------------------------------------------------------------------------- //
// The two canonical endpoints. `gate_id` travels in the path and nowhere else.
// --------------------------------------------------------------------------- //

/** `POST /gates/{gate}/decide` — the canonical APPROVAL AUTHORITY. */
export function decidePath(gateId: string): string {
  return `/gw/gates/${encodeURIComponent(gateId)}/decide`;
}

/** `POST /gates/{gate}/resolve` — the canonical LIFECYCLE TRANSITION. */
export function resolvePath(gateId: string): string {
  return `/gw/gates/${encodeURIComponent(gateId)}/resolve`;
}

// --------------------------------------------------------------------------- //
// Request bodies — server-authored values forwarded verbatim, and nothing else
// --------------------------------------------------------------------------- //

/** The exact `DecideBody` this surface sends. Deliberately a narrow subset of the server contract. */
export type DecideRequest = {
  readonly decision: GateDecision;
  /** Scoped to the EXACT canonical target. Never null/empty — that would mean "the whole batch". */
  readonly slot_ids: readonly string[];
  /** The EXACT server-authored artifact revision this decision approves. Never derived here. */
  readonly revision?: number;
  /** request_change only: the attributable rationale the canonical command requires. */
  readonly notes?: string;
};

/**
 * Build the decide request for ONE canonical target.
 *
 * WHY `slot_ids` IS ALWAYS EXPLICIT. `DecideBody.slot_ids` treats null/empty as "every still-target
 * slot" — a whole-batch action. A Final Review surface that omitted it while the operator believed
 * they were acting on one item would silently decide the entire gate. It is therefore always the exact
 * single canonical target, carried verbatim from the server-authored gate target list.
 *
 * WHY `revision` IS THE PREFLIGHT'S OWN `script_revision`. `engine.resolve` counts approvals only on
 * the EXACT current head revision; a NULL revision means "whatever the head is at resolve time". Since
 * the operator reviewed the immutable package the #447/#448 preflight pinned, forwarding that pin binds
 * the decision to the revision actually reviewed. If the head has since moved, the approval is
 * PRESERVED but does not advance the new head — the server's own fail-closed behaviour, reached by
 * telling it the truth rather than by a client-side check. The value is copied off the server-authored
 * tuple with no transformation: it is never derived, recomputed, or defaulted here.
 *
 * NOTHING ELSE IS SENT. No actor, approver, principal, role, assignment, quorum, authority or
 * eligibility field appears in this body, because the /gw route resolves and signs the principal
 * SERVER-SIDE and the gate API authorizes it against persisted Tanaghom authority.
 */
export function decideRequest(
  decision: GateDecision,
  tuple: ApprovalPreflightTuple,
  notes?: string,
): DecideRequest {
  const base: DecideRequest = {
    decision,
    slot_ids: [tuple.slot_id],
    revision: tuple.script_revision,
  };
  // The canonical command REQUIRES a comment for request_change (engine.decide raises without one).
  // Mirroring it here shapes the request; it does not enforce the rule — the server still refuses an
  // empty one, and this surface relays that refusal rather than pre-judging it.
  if (decision === "request_change") return { ...base, notes: notes ?? "" };
  return base;
}

/** The exact `ResolveBody` this surface sends: the single canonical target and nothing else. No
 *  `actor` — the signed principal is the server's to resolve, exactly as with decide. */
export type ResolveRequest = { readonly slot_ids: readonly string[] };

export function resolveRequest(slotId: string): ResolveRequest {
  return { slot_ids: [slotId] };
}

// --------------------------------------------------------------------------- //
// Presentation gating — which canonical step the SERVER's own truth admits next
// --------------------------------------------------------------------------- //

/** The server-authored per-target outcome carried by the canonical gate detail
 *  (`engine.get_gate` -> `targets[].current_outcome`). Mirrored, never defined here. */
export type TargetOutcome = "pending" | "approved" | "changes_requested" | "rejected";

/**
 * Why the DECISION control is or is not offered.
 *
 * Presentation gating ONLY. `offered` never means authorized, permitted, or certain to succeed: the
 * canonical command revalidates present state and authority when it runs and can still refuse. The
 * inverse matters more — a control is withheld only for a reason the SERVER stated, never because this
 * surface concluded something about the operator.
 */
export type DecideOffer =
  | { offered: true; reason: "offered"; tuple: ApprovalPreflightTuple }
  | {
      offered: false;
      reason: "no_open_gate" | "not_a_gate_target" | "no_complete_tuple" | "target_mismatch";
    };

/**
 * Decide whether the canonical decision control may be OFFERED for this target.
 *
 * Fail-closed, in order:
 *   • no open canonical gate for this stage — there is no authority endpoint to address;
 *   • the slot is not among the gate's server-authored targets — REFUSE rather than send a slot the
 *     gate does not govern (the server would reject it; asking is still wrong);
 *   • no complete six-member package tuple — the exact revision binding cannot be forwarded verbatim,
 *     and a partial or defaulted pin is never assembled;
 *   • the tuple identifies a different (gate, slot) than this target — REFUSE. Nothing is reconciled,
 *     chosen, or substituted.
 */
export function decideOffer(
  gateId: string | null | undefined,
  slotId: string,
  gateTargetIds: readonly string[],
  tuple: ApprovalPreflightTuple | null | undefined,
): DecideOffer {
  if (!gateId) return { offered: false, reason: "no_open_gate" };
  if (!gateTargetIds.includes(slotId)) return { offered: false, reason: "not_a_gate_target" };
  if (!tuple) return { offered: false, reason: "no_complete_tuple" };
  for (const value of [tuple.snapshot_id, tuple.workflow_version_id, tuple.gate_id, tuple.slot_id]) {
    if (typeof value !== "string" || value.trim() === "") {
      return { offered: false, reason: "no_complete_tuple" };
    }
  }
  if (!Number.isInteger(tuple.topic_revision) || !Number.isInteger(tuple.script_revision)) {
    return { offered: false, reason: "no_complete_tuple" };
  }
  if (tuple.gate_id !== gateId || tuple.slot_id !== slotId) {
    return { offered: false, reason: "target_mismatch" };
  }
  return { offered: true, reason: "offered", tuple };
}

/**
 * Why the ADVANCE (resolve) control is or is not offered.
 *
 * DECISION-BEFORE-RESOLVE IS PRESERVED HERE AS PRESENTATION, AND UPSTREAM AS AUTHORITY. The control is
 * withheld until the server's OWN gate detail reports a recorded outcome for this target, so the UI
 * cannot invite a transition over an undecided item. That is a mirror of the canonical ordering, not a
 * second implementation of it: `engine.resolve` applies the quorum itself and an undecided slot is
 * looped back regardless of what any client believed.
 */
export type AdvanceOffer =
  | { offered: true; reason: "offered" }
  | { offered: false; reason: "no_open_gate" | "not_a_gate_target" | "no_decision_recorded" };

export function advanceOffer(
  gateId: string | null | undefined,
  slotId: string,
  gateTargetIds: readonly string[],
  outcome: TargetOutcome | string | null | undefined,
): AdvanceOffer {
  if (!gateId) return { offered: false, reason: "no_open_gate" };
  if (!gateTargetIds.includes(slotId)) return { offered: false, reason: "not_a_gate_target" };
  // Anything that is not a server-authored recorded outcome — including an unknown value from a drifted
  // contract — withholds the control. Fail closed: an unrecognized outcome is never read as "decided".
  const decided = outcome === "approved" || outcome === "changes_requested" || outcome === "rejected";
  if (!decided) return { offered: false, reason: "no_decision_recorded" };
  return { offered: true, reason: "offered" };
}

/** Neutral copy for a withheld control. States the SERVER's position or a structural fact, claims no
 *  authority, and never tells the operator what they may or may not do. */
export const DECIDE_OFFER_COPY: Record<DecideOffer["reason"], string> = {
  offered:
    "The canonical gate decision may be attempted for this target. That is not a statement that it " +
    "will be accepted: the command revalidates present state and authority when it runs.",
  no_open_gate:
    "The server reports no open canonical gate for this stage, so no decision request is offered.",
  not_a_gate_target:
    "This item is not among the canonical gate's server-authored targets, so no decision request is " +
    "offered for it here.",
  no_complete_tuple:
    "The server did not return a complete six-member package tuple, so the exact reviewed revision " +
    "cannot be forwarded verbatim. A partial package binding is never assembled here.",
  target_mismatch:
    "The server-authored package tuple identifies a different gate/slot than this target, so no " +
    "request is sent. This surface reconciles nothing.",
};

export const ADVANCE_OFFER_COPY: Record<AdvanceOffer["reason"], string> = {
  offered:
    "The canonical lifecycle transition may be attempted for this target. It is a separate, explicit " +
    "operation: the server applies the governed quorum and decides what actually moves.",
  no_open_gate:
    "The server reports no open canonical gate for this stage, so no transition request is offered.",
  not_a_gate_target:
    "This item is not among the canonical gate's server-authored targets, so no transition request " +
    "is offered for it here.",
  no_decision_recorded:
    "The server reports no recorded decision for this target yet. The canonical transition applies " +
    "decisions; it does not make them, so it is not offered before one exists.",
};

// --------------------------------------------------------------------------- //
// Result classification — the same four-class discipline as the sign-off surface
// --------------------------------------------------------------------------- //

/** The canonical decide success body.
 *
 *  `gates/api.py` returns `{"touched": engine.decide(...)}`, and `engine.decide` returns
 *  `sorted(chosen)` — the SORTED LIST OF SLOT IDS the decision was recorded over, NOT a count. That
 *  distinction is load-bearing and is exactly the kind of thing a stub cannot teach you: an earlier
 *  revision of this module validated `touched` as an integer, which would have classified every real
 *  canonical success as contract drift and rendered a recorded decision as an unresolved one. The
 *  shape is mirrored from the server here; it is not defined here. */
export type DecideAccepted = { readonly touched: readonly string[] };

/** The canonical resolve success body (`gates/api.py` -> `{"outcomes": {slot_id: outcome}}`). */
export type ResolveAccepted = { readonly outcomes: Readonly<Record<string, string>> };

export type AdvancementResult<T> =
  /** The server applied the canonical operation and authored this result. */
  | { kind: "accepted"; value: T }
  /** A server-authored refusal, relayed VERBATIM. Never reinterpreted into a local conclusion. */
  | { kind: "refused"; status: number; detail: string }
  /** V2's OWN /gw boundary declined before any upstream request. Not a server decision. */
  | { kind: "seam_refusal"; status: number; detail: string }
  /** The request never produced a response. Whether it reached the server is UNKNOWN. */
  | { kind: "transport"; detail: string }
  /** Contract drift: a success body outside the canonical shape. Fails closed, neutral. */
  | { kind: "contract_drift"; status: number; detail: string };

/**
 * Classify a decide 200.
 *
 * `touched` must be an array of non-blank slot-id strings — the server's own list of the targets the
 * decision was recorded over. Anything else is drift rather than a decision: rendering a malformed
 * body as an accepted decision is precisely the fabricated success this lane exists to avoid.
 *
 * An EMPTY list is canonical and meaningful (the decision matched no still-target slot), so it is not
 * treated as drift. The surface renders the list verbatim and concludes nothing further from it.
 */
export function classifyDecideSuccess(body: unknown): AdvancementResult<DecideAccepted> {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { kind: "contract_drift", status: 200, detail: "the decide response is not an object" };
  }
  const touched = (body as Record<string, unknown>).touched;
  if (!Array.isArray(touched)) {
    return {
      kind: "contract_drift",
      status: 200,
      detail: "the decide response does not carry a canonical `touched` list of slot ids",
    };
  }
  if (!touched.every((t) => typeof t === "string" && t.trim() !== "")) {
    return {
      kind: "contract_drift",
      status: 200,
      detail: "the decide response carries a `touched` entry that is not a slot id",
    };
  }
  return { kind: "accepted", value: { touched: touched as string[] } };
}

/**
 * Classify a resolve 200.
 *
 * `outcomes` is the server's per-slot transition ledger. It is accepted only as an object of string
 * values — the surface renders it verbatim and draws no lifecycle conclusion of its own from it. An
 * EMPTY ledger is canonical and meaningful (the server moved nothing), so it is not treated as drift.
 */
export function classifyResolveSuccess(body: unknown): AdvancementResult<ResolveAccepted> {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return { kind: "contract_drift", status: 200, detail: "the resolve response is not an object" };
  }
  const outcomes = (body as Record<string, unknown>).outcomes;
  if (!outcomes || typeof outcomes !== "object" || Array.isArray(outcomes)) {
    return {
      kind: "contract_drift",
      status: 200,
      detail: "the resolve response does not carry a canonical `outcomes` map",
    };
  }
  for (const value of Object.values(outcomes as Record<string, unknown>)) {
    if (typeof value !== "string") {
      return {
        kind: "contract_drift",
        status: 200,
        detail: "the resolve response carries a non-string outcome value",
      };
    }
  }
  return { kind: "accepted", value: { outcomes: outcomes as Record<string, string> } };
}

/**
 * Classify a failed attempt into exactly one of the non-success classes.
 *
 * The discrimination is STRUCTURAL, mirroring `lib/sign-off-action.ts`:
 *   • `status === 0`          — `postJson`'s own catch: no response at all -> TRANSPORT.
 *   • a /gw prose refusal     — V2's boundary declined (403 not-in-write-boundary, 501 non-dev
 *                               runtime, 503 api unreachable) BEFORE any upstream request. The gate
 *                               API raises `HTTPException(status, "<prose>")` for decide/resolve, so
 *                               both arrive as `detail` prose and are separated by STATUS + the fact
 *                               that only the seam emits these three.
 *   • anything else with prose— a server-authored refusal, relayed verbatim.
 *
 * WHY THERE IS NO CANONICAL CODE VOCABULARY HERE, UNLIKE SIGN-OFF. `/gates/{id}/decide` and
 * `/resolve` raise `HTTPException(status, str(e))` — prose, not `{"error": code}`. Inventing a code
 * vocabulary for them would be V2 authoring server semantics. The prose is therefore relayed
 * unchanged and no meaning is derived from it.
 */
export function classifyAdvancementFailure<T>(err: WriteError): AdvancementResult<T> {
  if (err.status === 0) {
    return { kind: "transport", detail: err.message || "the request did not reach the server" };
  }
  const body = err.detail as { detail?: unknown } | undefined;
  const prose = body && typeof body.detail === "string" ? body.detail : null;
  // The three statuses V2's OWN boundary emits before any upstream request. 403 = path not in the
  // write boundary; 501 = signing refused outside a declared dev/test runtime; 503 = the seam could
  // not reach the API at all. Upstream decide/resolve use 400/409 exclusively, so these do not
  // collide — and a seam refusal must never be rendered as though authority denied the operator.
  if (err.status === 403 || err.status === 501 || err.status === 503) {
    return { kind: "seam_refusal", status: err.status, detail: prose ?? "the workbench boundary declined this request" };
  }
  if (prose) return { kind: "refused", status: err.status, detail: prose };
  return {
    kind: "contract_drift",
    status: err.status,
    detail: "the server returned a failure in an unrecognized shape",
  };
}

/** Copy for the classes that are NOT server decisions about this target. */
export function advancementNonAcceptedCopy(kind: AdvancementResult<unknown>["kind"]): string {
  switch (kind) {
    case "refused":
      return (
        "The canonical command refused this request and its reason is shown verbatim. Nothing was " +
        "applied; re-read the server state before attempting again."
      );
    case "seam_refusal":
      return (
        "The workbench boundary declined to issue this request, so the canonical command was never " +
        "reached. This is not a decision and says nothing about authority or eligibility."
      );
    case "transport":
      return (
        "The request did not complete. Whether it reached the server is unknown, so nothing is " +
        "claimed about it here. Re-read the server state to see the authoritative outcome."
      );
    case "contract_drift":
      return (
        "The server returned a result this surface does not recognize. It is reported unchanged and " +
        "treated as unresolved; no outcome, authority, or lifecycle conclusion is inferred from it."
      );
    default:
      return "";
  }
}
