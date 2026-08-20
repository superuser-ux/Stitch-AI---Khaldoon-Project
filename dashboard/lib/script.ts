import type { Target } from "./review-context";

// #22 — the Scripts-stage hero should be the script's OWN opening (so two scripts under one topic are
// distinguishable), not the parent topic hook. Primary source: the `hook` structured beat; #149 — for
// registry-shaped structures (no `hook` key), the FIRST beat in the format's registry order IS the
// opening (e.g. Carousel `slide_1`, labeled "Hook" in the registry). Fallback: the first non-empty
// line of the full script text (`script_ar`). Never `final_line` (that is a closing line, not an
// opening). Pure, read-only — no writer/backend/data semantics are involved.
export function getScriptOpeningBeat(
  t: Pick<Target, "script_structure" | "script_ar">,
  structureOrder?: string[],
): { key: string | null; text: string | null } {
  const s = t.script_structure;
  if (s && typeof s === "object" && !Array.isArray(s)) {
    const hook = Object.entries(s).find(([key]) => key.toLowerCase() === "hook");
    if (hook && typeof hook[1] === "string" && hook[1].trim()) return { key: hook[0], text: hook[1].trim() };
    for (const key of structureOrder ?? []) {
      const value = (s as Record<string, unknown>)[key];
      if (typeof value === "string" && value.trim()) return { key, text: value.trim() };
    }
  }
  if (typeof t.script_ar === "string") {
    const line = t.script_ar.split(/\r?\n/).map((l) => l.trim()).find((l) => l.length > 0);
    if (line) return { key: null, text: line };
  }
  return { key: null, text: null };
}

export function getScriptOpening(
  t: Pick<Target, "script_structure" | "script_ar">,
  structureOrder?: string[],
): string | null {
  return getScriptOpeningBeat(t, structureOrder).text;
}
