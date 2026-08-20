// #16 / #104 — review-feed attribute filters (pure, presentation-only). Narrows an already-outcome-
// filtered visible feed by card ATTRIBUTES — pillar and content format — using fields already loaded on
// each Target. NO backend/API/schema, no fetch. Single-select per dimension; the two dimensions compose
// (AND). Kept React-free (mirrors lib/review-sort.ts, lib/review-search.ts) so it is unit-testable.
import type { Target } from "./review-context";

// null on a dimension = "all" (no constraint on that attribute).
export type AttrFilters = { pillar: string | null; format: string | null };

// A card passes when it matches every ACTIVE dimension. pillar is matched on the stable `pillar_code`;
// format on the `format` display name (both already on the loaded Target).
export function matchesAttrs(t: Target, { pillar, format }: AttrFilters): boolean {
  if (pillar && t.pillar_code !== pillar) return false;
  if (format && t.format !== format) return false;
  return true;
}

// Pure, non-mutating: returns the input unchanged when no dimension is active, else a new narrowed
// array preserving incoming order (so a downstream search/sort still fully controls the result).
export function filterFeed(feed: Target[], filters: AttrFilters): Target[] {
  if (!filters.pillar && !filters.format) return feed;
  return feed.filter((t) => matchesAttrs(t, filters));
}

// Distinct filter options present in the current feed, for populating the select controls.
// Pillars carry a stable `code` (the filter value) + a human `label`; formats are plain strings.
export function pillarOptions(targets: Target[]): { code: string; label: string }[] {
  const seen = new Map<string, string>();
  for (const t of targets) {
    if (t.pillar_code && !seen.has(t.pillar_code)) seen.set(t.pillar_code, t.pillar_name_en || t.pillar_code);
  }
  return [...seen].map(([code, label]) => ({ code, label })).sort((a, b) => a.label.localeCompare(b.label));
}

export function formatOptions(targets: Target[]): string[] {
  return [...new Set(targets.map((t) => t.format).filter((value): value is string => Boolean(value)))]
    .sort((a, b) => a.localeCompare(b));
}
