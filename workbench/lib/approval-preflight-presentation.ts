// #447 — pure presentation derivation for the Stage 4 approval-package preflight panel.
//
// The backend is the SOLE authority. These helpers turn ALREADY-AUTHORITATIVE typed fields into a
// presentation category and NEUTRAL copy. They reconstruct nothing, join nothing, re-rank nothing,
// reinterpret no reason code, and expand no reason-code meaning.
//
// Three invariants are enforced HERE so no panel branch can violate them by accident:
//
//   1. `available` (an eligibility VERDICT) and `status` (the HISTORICAL evidence status) are
//      DISTINCT facts and are never collapsed. A `recorded` history with a present-state denial is
//      NOT eligible; an `unknown_history` result is not "rejected".
//   2. The six-member tuple is presentable ONLY when the server returned all six. A partial tuple is
//      never assembled, never padded, and never shown — matching the server's own refusal to emit one.
//   3. NOTHING here ever states, implies, or hints that the viewer (or any principal) may act. The
//      human hard floor is a STRUCTURAL requirement about the stage, never a permission. The server
//      evaluates no caller (`authorization_evaluated` is always false) and this surface must read the
//      same way.
//
// Pure and JSX-free on purpose, so it is unit-testable under the existing workbench/scripts
// `node --experimental-strip-types` seam, exactly like lib/final-review-presentation.ts.

import type { ApprovalPreflight, ApprovalPreflightTuple } from "./read-model";

export type PreflightCategory =
  | "coherent" // fully pinned, governed, and presently eligible for human sign-off
  | "not_eligible" // history IS established, but a present-state / coherence check failed
  | "unknown_history" // required immutable proof is not established — its cause is NOT reconstructed
  | "unavailable"; // not an admitted canonical final-review target

export type PreflightVerdict = {
  category: PreflightCategory;
  copy: string;
  /** The server's deterministic primary reason. `null` only when coherent. Never re-derived. */
  primaryReason: string | null;
};

// Neutral copy per category. None of these asserts an action, a permission, an approval outcome, or a
// cause beyond what the authoritative fields already say.
const COPY: Record<PreflightCategory, string> = {
  coherent:
    "The immutable target package is fully pinned, governed by the current generation, and presently " +
    "eligible for human final-review sign-off.",
  not_eligible:
    "Recorded package evidence is established, but this target is not presently eligible. The server " +
    "supplied the reason below.",
  unknown_history:
    "Required immutable proof is not established; this surface does not reconstruct its cause.",
  unavailable: "Not an admitted canonical final-review target.",
};

/**
 * Derive the presentation verdict from the authoritative response.
 *
 * Precedence mirrors the server's own layering and never re-ranks it: typed `unavailable` and
 * `unknown_history` describe the HISTORICAL evidence and win; otherwise `available` decides whether an
 * established history is presently eligible. `reason_code` is taken verbatim as the primary reason —
 * the client never re-sorts `denials` or picks a different head.
 */
export function preflightVerdict(model: ApprovalPreflight): PreflightVerdict {
  if (model.status === "unavailable") {
    return { category: "unavailable", copy: COPY.unavailable, primaryReason: model.reason_code };
  }
  if (model.status === "unknown_history") {
    return { category: "unknown_history", copy: COPY.unknown_history, primaryReason: model.reason_code };
  }
  if (model.available) {
    return { category: "coherent", copy: COPY.coherent, primaryReason: null };
  }
  return { category: "not_eligible", copy: COPY.not_eligible, primaryReason: model.reason_code };
}

/** The six unconditional members, in the canonical order the server pins and the command binds. */
export const TUPLE_MEMBER_ORDER = [
  "gate_id",
  "slot_id",
  "snapshot_id",
  "topic_revision",
  "script_revision",
  "workflow_version_id",
] as const;

export type TuplePresentation =
  | { complete: true; members: { key: string; value: string }[] }
  | { complete: false; members: null };

/**
 * Present the six-member tuple, or refuse.
 *
 * A partially pinned package is NEVER presentable: if the server withheld the tuple (`null`) or any
 * member is missing/blank, this returns `{complete:false, members:null}` rather than rendering a
 * partial identity a reader could mistake for a complete pin. Values are stringified verbatim — never
 * defaulted, substituted, abbreviated, or re-derived.
 */
export function tuplePresentation(tuple: ApprovalPreflightTuple | null | undefined): TuplePresentation {
  if (!tuple) return { complete: false, members: null };
  const members: { key: string; value: string }[] = [];
  for (const key of TUPLE_MEMBER_ORDER) {
    const value = (tuple as Record<string, unknown>)[key];
    if (value === null || value === undefined || String(value).trim() === "") {
      return { complete: false, members: null };
    }
    members.push({ key, value: String(value) });
  }
  return { complete: true, members };
}

/**
 * Neutral copy for the STRUCTURAL human hard floor.
 *
 * This describes the STAGE's requirement, never a principal's permission. It deliberately has no
 * "you may sign off" / "awaiting your approval" form: the server evaluates no caller, so the surface
 * must not imply one has been evaluated.
 */
export function humanAuthorityCopy(
  finalReview: ApprovalPreflight["evidence"]["final_review"],
): string {
  if (!finalReview) return "The server supplied no final-review authority evidence.";
  return finalReview.human_signoff_required
    ? "This stage requires human sign-off (server-enforced hard floor). No principal has been evaluated here."
    : "The server does not currently assert a human hard floor for this stage. No principal has been evaluated here.";
}
