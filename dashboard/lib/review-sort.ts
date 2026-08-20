// #16 / #96 — review-feed sorting (pure, presentation-only). Reorders an ALREADY-derived, already-
// filtered visible feed using fields already loaded on each Target — NO new backend/API/data
// dependency. Kept React-free (outcome is injected, not read from context) so it is unit-testable in
// isolation, mirroring lib/stages.ts and lib/content-id.ts.
//
// Options and the fields each uses:
//   default — leave the feed in its incoming `orderedTargets` order (which is already pending-first by
//             gate order). No re-sort → existing behavior is preserved exactly.
//   pending — pending/unresolved cards first, then day → time → slot_id within each group (a MORE
//             meaningful, still-deterministic stable fallback than default's raw gate order).
//   daytime — strict schedule order: day → time_uae → slot_id. Ignores review outcome.
//   code    — content-code order via contentIdKey (pillar+struggle+day+post), slot_id as tiebreak.
import { contentIdKey } from "./content-id";
import type { Target } from "./review-context";

export type SortMode = "default" | "pending" | "daytime" | "code";

export const SORT_OPTIONS: { key: SortMode; label: string }[] = [
  { key: "default", label: "Default" },
  { key: "pending", label: "Pending first" },
  { key: "daytime", label: "Day / time" },
  { key: "code", label: "Content code" },
];

// Stable schedule comparator — the deterministic fallback shared by daytime + pending sorts.
export const byDayTime = (a: Target, b: Target) =>
  a.day - b.day || a.time_uae.localeCompare(b.time_uae) || a.slot_id.localeCompare(b.slot_id);

// Pure, non-mutating: returns a NEW array (or the input unchanged for "default"). JS Array.sort is
// stable (ES2019+), so equal-key cards preserve the incoming (already-filtered) order. `outcomeOf`
// is injected so this module never depends on React/context — the caller passes the same staged
// outcome resolver that produces the #55 filter + disposition counts, keeping ordering consistent.
export function sortFeed(
  feed: Target[],
  mode: SortMode,
  outcomeOf: (t: Target) => Target["current_outcome"],
): Target[] {
  if (mode === "default") return feed;
  const arr = [...feed];
  if (mode === "daytime") return arr.sort(byDayTime);
  if (mode === "code") {
    return arr.sort((a, b) => contentIdKey(a).localeCompare(contentIdKey(b)) || a.slot_id.localeCompare(b.slot_id));
  }
  // pending-first, day/time within each group
  const rank = (t: Target) => (outcomeOf(t) === "pending" ? 0 : 1);
  return arr.sort((a, b) => rank(a) - rank(b) || byDayTime(a, b));
}
