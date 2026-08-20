// #17 — the topic "Why now" rationale is reviewer-facing advisory copy. In stub/demo generation it is a
// self-describing placeholder ("concise reason" / the prompt echo), which reads as noise. This filters
// those known low-signal values out of the UI without hiding a genuine reviewer justification. Display
// concern only — it does not change generation or review semantics.
const PLACEHOLDER_FRAGMENTS = [
  "concise reason",
  "why this topic now",
  "concise, for the reviewer",
  "سبب مختصر",
  "ليش هاد الموضوع الآن",
  "مختصر للمراجِع",
];

// true when the rationale carries real reviewer signal (i.e. is not empty and not a known placeholder).
export function isMeaningfulRationale(s: string | null | undefined): boolean {
  if (!s) return false;
  const t = s.trim();
  if (!t) return false;
  const lower = t.toLowerCase();
  return !PLACEHOLDER_FRAGMENTS.some((p) => lower.includes(p.toLowerCase()));
}
