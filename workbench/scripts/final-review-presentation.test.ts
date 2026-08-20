// #433 — focused unit + type validation for the final-review NULL-group presentation mapping.
// Pure functions; no browser, no network, no stack. Run:
//   node --experimental-strip-types scripts/final-review-presentation.test.ts
// Kept out of e2e/ so Playwright never collects it (mirrors scripts/product-surface.test.ts).
import { strict as assert } from "node:assert";
import { nullGroupPresentation } from "../lib/final-review-presentation.ts";

let failures = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`  [PASS] ${name}`);
  else {
    failures += 1;
    console.log(`  [FAIL] ${name}`);
  }
}

// Copy must NEVER invent a cause or a negative/positive evidence claim from the null itself.
const FORBIDDEN = [
  "legacy",
  "snapshot",
  "no recorded",
  "no immutable",
  "no governing",
  "no decision",
  "no coverage",
  "attached before",
  "rejection",
  "non-approval",
  "no activity",
  "empty",
];
function noForbidden(copy: string): boolean {
  const c = copy.toLowerCase();
  return FORBIDDEN.every((f) => !c.includes(f));
}

console.log("#433 final-review NULL-group presentation");

// 1 — top-level unavailable + null groups (no per-group status): each group is `unavailable`, and the
//     copy never claims legacy / unknown-history / missing-snapshot / no-evidence / rejection / no-activity.
{
  const p = nullGroupPresentation("unavailable"); // assignment/decision null: no per-group status
  const pk = nullGroupPresentation("unavailable", undefined); // package null with no status
  check("unavailable → category unavailable (group)", p.category === "unavailable");
  check("unavailable → category unavailable (package null)", pk.category === "unavailable");
  check("unavailable copy invents no cause / negative claim", noForbidden(p.copy) && noForbidden(pk.copy));
  check("unavailable copy is not an unknown_history claim", !p.copy.toLowerCase().includes("unknown history"));
}

// 2 — top-level unknown_history + null groups: typed unknown history is PRESERVED, with no invented
//     missing-snapshot / package-history / decision-history cause.
{
  const p = nullGroupPresentation("unknown_history");
  check("unknown_history → category unknown_history", p.category === "unknown_history");
  check("unknown_history copy invents no missing-snapshot/legacy/decision cause", noForbidden(p.copy));
}

// 3 — recorded projection with a null group and NO per-group status → absent-with-unknown-cause; never
//     a negative evidence claim.
{
  const p = nullGroupPresentation("recorded");
  check("recorded + null group → absent_unknown_cause", p.category === "absent_unknown_cause");
  check("absent_unknown_cause copy makes no negative claim", noForbidden(p.copy));
  check("absent_unknown_cause is not unknown_history/unavailable", p.category !== "unknown_history" && p.category !== "unavailable");
}

// 4 — an authoritative PER-GROUP status takes precedence over the top-level fallback and remains
//     independently authoritative (package supplies its own status even when top-level is recorded).
{
  const uh = nullGroupPresentation("recorded", "unknown_history");
  const ua = nullGroupPresentation("recorded", "unavailable");
  check("per-group unknown_history wins over recorded top", uh.category === "unknown_history");
  check("per-group unavailable wins over recorded top", ua.category === "unavailable");
  check("per-group status precedence copy invents no cause", noForbidden(uh.copy) && noForbidden(ua.copy));
}

// 5 — the three categories are distinct and stable (independent, typed distinctions never collapse).
{
  const cats = new Set([
    nullGroupPresentation("unavailable").category,
    nullGroupPresentation("unknown_history").category,
    nullGroupPresentation("recorded").category,
  ]);
  check("unavailable / unknown_history / absent_unknown_cause stay distinct", cats.size === 3);
}

console.log(failures === 0 ? "\nALL #433 presentation checks PASSED" : `\nFAILED (${failures})`);
process.exit(failures === 0 ? 0 : 1);
