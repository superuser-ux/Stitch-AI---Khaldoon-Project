// #315 Stage 2B-3 — V2-OWNED bilingual presentation (Codex ruling 1).
//
// Deterministic four-state presentation of an (Arabic, English) pair exposed by the canonical read
// models. This is V2's OWN utility: it preserves the #280 (V1 `dashboard/lib/bilingual.ts`) semantics
// as a REFERENCE only — there is NO V1 import, runtime dependency, or fallback into V1. It never
// fabricates a missing counterpart value; a single-side pair is disclosed explicitly and truthfully.

export type BilingualState = "bilingual" | "arabic-only" | "english-only" | "missing";

export type BilingualPresentation = {
  readonly state: BilingualState;
  readonly ar: string | null; // the present Arabic value (raw, unmodified) or null
  readonly en: string | null; // the present English value (raw, unmodified) or null
  readonly disclosure: string | null; // explicit fallback/absence disclosure; null iff both sides present
};

const present = (v?: string | null): v is string => v != null && v !== "";

/**
 * Deterministic 4-state presentation of an (Arabic, English) pair. The values are returned RAW (never
 * normalized) so a caller renders exactly the canonical bytes with the correct per-node lang/dir. A
 * missing side is NEVER invented — it is disclosed.
 */
export function presentBilingual(ar?: string | null, en?: string | null): BilingualPresentation {
  const a = present(ar) ? ar : null;
  const e = present(en) ? en : null;
  if (a !== null && e !== null) return { state: "bilingual", ar: a, en: e, disclosure: null };
  if (a !== null) return { state: "arabic-only", ar: a, en: null, disclosure: "English not provided — not fabricated" };
  if (e !== null) return { state: "english-only", ar: null, en: e, disclosure: "Arabic not provided — not fabricated" };
  return { state: "missing", ar: null, en: null, disclosure: "not provided in either language" };
}
