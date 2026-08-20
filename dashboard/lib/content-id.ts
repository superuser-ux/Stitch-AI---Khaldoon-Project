// #49 (BUG-003) — bidirectional resolution between the two identifier spaces of a content item.
//
//   • slot_id       — the CANONICAL internal id (e.g. "RE2E-1", "R205-D01-AM"). Authoritative, never
//                     derived. It is the source of truth everywhere downstream.
//   • content code  — the human-facing id shown on cards, DERIVED from the slot's placement
//                     (pillar · struggle/seq · day · post): compact "01-02-01.01" or
//                     expanded "P01-HS02-01.01". This is what an operator reads off the screen and
//                     quotes back in search / a command / an agent instruction.
//
// UNIQUENESS SCOPE: content codes are unique WITHIN A ROUND — the (day, post) pair identifies exactly
// one slot in a round, and pillar/struggle are attributes of that slot. Codes are NOT globally unique
// across rounds (every round has a "day 01 / post 01"). `resolveContentId` therefore resolves against a
// caller-supplied, round-scoped target set and REJECTS ambiguity / misses rather than guessing.

export type ContentIdMode = "compact" | "expanded" | "detailed";

// The minimal shape needed to derive a content code. `Target` (review-context) is structurally
// compatible, so callers pass their targets directly without an import cycle.
export interface ContentIdTarget {
  day: number;
  slot_id: string;
  pillar_short_code: string;
  seq_in_pillar: number;
  // #292 — the SERVER-AUTHORITATIVE code from the round's accepted display mapping generation.
  // When present it WINS over the derivation below, for display AND for resolution: a governed
  // reorder renumbers presentation, and the client must never show or resolve a code the server no
  // longer accepts. Absent = a legacy round with no generation, where the derivation remains
  // authoritative exactly as before (preservation by absence).
  display_code?: string | null;
}

/** #292 — split a server display_code ("P01-HS02-01.01") back into parts, so the compact form and
 *  the comparable key stay consistent with a derived code. Returns null if it is not that shape. */
function serverCodeParts(code: string | null | undefined) {
  const m = (code || "").match(/^P?(\d{2})-(?:HS)?(\d{2})-(\d{2})\.(\d{2})$/);
  return m ? { pillar: m[1], struggle: m[2], day: m[3], post: m[4] } : null;
}

function pad2(value: number | string) {
  return String(value).padStart(2, "0");
}

export function contentIdParts(target: ContentIdTarget) {
  // #292 — server truth first: an accepted mapping generation owns the code.
  const fromServer = serverCodeParts(target.display_code);
  if (fromServer) return fromServer;
  const pillarMatch = target.pillar_short_code?.match(/(\d+)/);
  const slotSuffix = target.slot_id.split("-").pop() || "";
  const pillar = pad2(pillarMatch?.[1] || "0");
  const struggle = pad2(target.seq_in_pillar || 0);
  let post = "01";
  if (slotSuffix === "PM") post = "02";
  else {
    const slotMatch = slotSuffix.match(/^S(\d+)$/);
    if (slotMatch) post = pad2(slotMatch[1]);
  }
  const day = pad2(target.day || 0);
  return { pillar, struggle, day, post };
}

export function contentIdLabel(target: ContentIdTarget, mode: ContentIdMode) {
  const parts = contentIdParts(target);
  const suffix = `${parts.day}.${parts.post}`;
  if (mode === "compact") return `${parts.pillar}-${parts.struggle}-${suffix}`;
  return `P${parts.pillar}-HS${parts.struggle}-${suffix}`;
}

// The canonical 8-digit key of a content code (pillar+struggle+day+post). Invariant to display
// formatting (compact vs expanded), separators, and the P/HS prefixes — the comparable form used for
// resolution, so "01-02-01.01", "P01-HS02-01.01", and "01 02 01 01" all resolve to the same slot.
export function contentIdKey(target: ContentIdTarget): string {
  const p = contentIdParts(target);
  return `${p.pillar}${p.struggle}${p.day}${p.post}`;
}

export type ContentIdResolution =
  | { ok: true; slot_id: string }
  | { ok: false; reason: "empty" | "not_found" | "ambiguous"; matches: string[] };

// Resolve EITHER identifier — a canonical slot_id OR a displayed content code (any display form) — to a
// single slot_id within the given round-scoped target set. A canonical slot_id match wins over a code
// match. It NEVER guesses: 0 matches → not_found, >1 → ambiguous (all candidate slot_ids listed),
// blank → empty. This is the inverse of contentIdLabel(); together they are the bidirectional mapping.
export function resolveContentId(targets: ContentIdTarget[], query: string): ContentIdResolution {
  const raw = (query ?? "").trim();
  if (!raw) return { ok: false, reason: "empty", matches: [] };
  const qUpper = raw.toUpperCase();
  const qDigits = raw.replace(/\D/g, "");
  const matches = new Set<string>();
  for (const t of targets) {
    if (t.slot_id.toUpperCase() === qUpper) { matches.add(t.slot_id); continue; }   // canonical exact wins
    if (qDigits.length === 8 && contentIdKey(t) === qDigits) matches.add(t.slot_id); // displayed content code
  }
  const arr = [...matches].sort();
  if (arr.length === 0) return { ok: false, reason: "not_found", matches: [] };
  if (arr.length > 1) return { ok: false, reason: "ambiguous", matches: arr };
  return { ok: true, slot_id: arr[0] };
}
