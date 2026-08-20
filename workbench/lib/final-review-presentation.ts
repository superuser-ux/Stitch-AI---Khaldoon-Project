// #433 — pure presentation-category derivation for the final-review projection panel's NULL evidence
// groups (package / assignment / decision).
//
// A null (absent) group MUST NOT, by itself, infer legacy data, unknown history, a missing snapshot,
// absent recorded evidence, rejection, non-approval, no activity, or any other negative/positive
// evidentiary claim. This helper derives a presentation category and NEUTRAL copy SOLELY from
// authoritative projection fields (the top-level status plus any per-group status the projection
// itself supplied). It reconstructs nothing, reinterprets no reason code, performs no join or API
// call or current-state lookup, and never expands reason-code meaning.
//
// Pure and JSX-free on purpose, so it is unit-testable under the existing workbench/scripts
// `node --experimental-strip-types` seam (see workbench/scripts/final-review-presentation.test.ts),
// exactly like lib/product-surface.ts + scripts/product-surface.test.ts.

import type { FinalReviewStatus } from "./read-model";

export type NullGroupCategory =
  | "unavailable" // the projection itself is unavailable (e.g. non-final-review / non-admitted target)
  | "unknown_history" // authoritative typed unknown history — its cause is NOT reconstructed
  | "absent_unknown_cause"; // the group is absent and the projection supplies no cause for it

export type NullGroupPresentation = { category: NullGroupCategory; copy: string };

// Neutral copy per category. None of these asserts WHY a group is absent beyond what the authoritative
// status already says; none claims legacy/missing-snapshot/no-evidence/rejection/no-activity.
const COPY: Record<NullGroupCategory, string> = {
  unavailable: "Not available in this projection.",
  unknown_history: "Typed unknown history; the projection does not reconstruct its cause.",
  absent_unknown_cause: "Absent; no cause is supplied by this projection.",
};

/**
 * Derive how to present a NULL / absent evidence group.
 *
 * @param topStatus   the authoritative top-level projection status.
 * @param groupStatus the group's OWN authoritative status when the group object supplied one (e.g.
 *                    `package.status`); `undefined`/`null` when the whole group object is null.
 *
 * Precedence: an authoritative per-group status wins; otherwise the top-level status categorises the
 * absence; a null group under a `recorded` (or any non-`unavailable`/non-`unknown_history`) projection
 * is `absent_unknown_cause`. It is NEVER a legacy / missing-snapshot / no-recorded-evidence / negative
 * claim, and `unavailable` (typed unavailability) is never turned into a negative-evidence statement.
 */
export function nullGroupPresentation(
  topStatus: FinalReviewStatus,
  groupStatus?: string | null,
): NullGroupPresentation {
  if (groupStatus === "unknown_history") return { category: "unknown_history", copy: COPY.unknown_history };
  if (groupStatus === "unavailable") return { category: "unavailable", copy: COPY.unavailable };
  if (topStatus === "unavailable") return { category: "unavailable", copy: COPY.unavailable };
  if (topStatus === "unknown_history") return { category: "unknown_history", copy: COPY.unknown_history };
  return { category: "absent_unknown_cause", copy: COPY.absent_unknown_cause };
}
