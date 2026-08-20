// #280 — the deterministic, RTL-safe presentation contract for the existing structured bilingual
// fields (topic/script/name `_ar` + `_en`). PRESENTATION ONLY: it never parses, merges, mutates, or
// persists source content, and never invents a translation. It only decides, for display:
//   • which stored value to show when one side is missing (deterministic fallback), and
//   • the correct direction + language tag for whatever value is shown (RTL safety), and
//   • how to expose a genuinely-absent value truthfully (no silent blank).
//
// Arabic is the product's content-primary language, so `primary` defaults to "ar"; operator-facing
// catalogue labels (pillar / struggle names) pass primary:"en". Nothing here changes review or
// generation semantics.

export const BILINGUAL_SEPARATOR = " · ";

export type Bidi = "rtl" | "ltr";
export type Lang = "ar" | "en";

export function dirForLang(lang: Lang): Bidi {
  return lang === "ar" ? "rtl" : "ltr";
}

export type BilingualPick =
  | { text: string; lang: Lang; dir: Bidi; present: true }
  | { text: null; lang: null; dir: null; present: false };

function clean(value: string | null | undefined): string | null {
  if (value == null) return null;
  const t = value.trim();
  return t ? t : null;
}

// Deterministically choose the value to display from a bilingual pair. Prefers `primary`; falls back
// to the other side only when the primary is absent/blank; returns present:false when BOTH are absent
// so the caller can render a truthful "not available" rather than an empty node.
export function composeBilingual(
  ar: string | null | undefined,
  en: string | null | undefined,
  opts?: { primary?: Lang },
): BilingualPick {
  const primary: Lang = opts?.primary ?? "ar";
  const values: Record<Lang, string | null> = { ar: clean(ar), en: clean(en) };
  const order: Lang[] = primary === "ar" ? ["ar", "en"] : ["en", "ar"];
  for (const lang of order) {
    const text = values[lang];
    if (text) return { text, lang, dir: dirForLang(lang), present: true };
  }
  return { text: null, lang: null, dir: null, present: false };
}
