// #16 / #98 — review-feed text search (pure, presentation-only). Narrows an already-filtered visible
// feed to cards whose already-loaded text matches a query — NO backend/API/schema, no fetch. Simple and
// deterministic: case-insensitive substring over normalized whitespace, no fuzzy/ranking/highlighting.
// Kept React-free (mirrors lib/review-sort.ts, lib/content-id.ts) so it is unit-testable in isolation.
import { contentIdKey, contentIdLabel } from "./content-id";
import type { Target } from "./review-context";

// trim, lowercase, collapse internal whitespace. Empty (or whitespace-only) → "" means "no search".
export function normalizeQuery(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, " ");
}

// The human-meaningful, already-loaded text of a card: its identifiers (canonical slot_id + the
// displayed content code, both forms) and its visible copy (hook/angle/body, rationale, script, and
// the pillar/format/lens labels). All fields come off the loaded Target — nothing joined or fetched.
export function searchableText(t: Target): string {
  const identifiers = [t.slot_id, contentIdKey(t), contentIdLabel(t, "compact"), contentIdLabel(t, "expanded")];
  const copy = [
    t.hook_text, t.topic_angle, t.rationale_ar, t.rationale_en, t.script_ar, t.final_line,
    t.pillar_name_en, t.pillar_name_ar, t.hcs_name_en, t.format, t.lens_name_en,
  ];
  return [...identifiers, ...copy].filter(Boolean).join(" • ").toLowerCase();
}

// A card matches when the normalized query is a substring of its searchable text. An empty query
// matches everything (so "no query" behaves exactly like "no search").
export function matchesQuery(t: Target, normalizedQuery: string): boolean {
  if (!normalizedQuery) return true;
  return searchableText(t).includes(normalizedQuery);
}

// Pure, non-mutating: returns the input unchanged for an empty query, else a new narrowed array that
// preserves incoming order (so a downstream sort still fully controls ordering).
export function searchFeed(feed: Target[], rawQuery: string): Target[] {
  const query = normalizeQuery(rawQuery);
  if (!query) return feed;
  return feed.filter((t) => matchesQuery(t, query));
}
