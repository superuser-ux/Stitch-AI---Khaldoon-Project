// #382 — the SINGLE typed V2 lens matrix + the SINGLE pure lens resolver.
//
// Ruling 2 (Codex reconciliation 5071383590) / amendment §A: ONE typed three-class matrix governs
// LENSES only (stages stay derived from `/workflow-stages/active-enabled`, see lib/stage-rail.ts).
// This module is the SOLE source for lens rendering, navigation, accessibility state and URL
// validation. The same pure functions serve initial render, click, keyboard, reload and popstate —
// there is no second lens authority anywhere. Before #382 the lens choice was resolved in two places
// (the global `?lens=` in run-workspace via the old stage-lens-matrix, and the per-run
// `?lens_{roundId}=` inline in run-schedule-workspace); both are consolidated here without changing
// either param's existing meaning.
//
// THREE CLASSES (amendment §A), never two:
//   - implemented-enabled       : a real surface exists AND it is valid for the current gate → navigable.
//   - implemented-context-invalid: the surface exists but not for THIS gate (e.g. Calendar on Topics,
//                                  Overview on Schedule) → visible, disabled, truthful reason, never
//                                  navigates. This is the class the old binary matrix could not express.
//   - unimplemented-disabled    : never built in this transition lane (Workflow, Inbox, Board,
//                                  Analytics) →
//                                  visible, disabled, truthful reason. NON-GOAL: nothing here is built
//                                  "solely to activate a menu entry" (issue Non-goals / ruling 8).
//
// FAIL CLOSED (amendment §B): an unknown / disabled / context-invalid `?lens=` value never renders a
// stale or invalid view — `resolveLens` returns the gate's default and the shell canonicalizes the URL
// with `replace` (never `push`) plus an accessible notice.

/** Governed gate stages that own a lens menu. Keyed by `gate_stage` (see lib/stage-rail.ts), the same
 *  canonical identity the panels route on. Scripts (`script_review`) has no lens menu. */
export type LensGate = "schedule_review" | "topic_review";

export type LensKey =
  | "calendar"
  | "grid"
  | "list"
  | "overview"
  | "workflow"
  | "inbox"
  | "board"
  | "analytics";

export type LensClass =
  | "implemented-enabled"
  | "implemented-context-invalid"
  | "unimplemented-disabled";

export type LensEntry = {
  readonly key: LensKey;
  readonly label: string;
  readonly cls: LensClass;
  /** true only for implemented-enabled. The single flag the menu binds disabled/aria state to. */
  readonly navigable: boolean;
  /** Truthful reason shown for any non-navigable entry (both disabled classes). */
  readonly reason?: string;
};

// The canonical top-menu order — the "views" an operator scans left-to-right. Stable across gates so
// the menu never reflows its entries; only each entry's CLASS changes with context.
const LENS_ORDER: readonly LensKey[] = [
  "calendar", "grid", "list", "overview", "workflow", "inbox", "board", "analytics",
];

const LABEL: Record<LensKey, string> = {
  calendar: "Calendar", grid: "Grid", list: "List", overview: "Overview",
  workflow: "Workflow", inbox: "Inbox", board: "Board", analytics: "Analytics",
};

/** Lenses that have a REAL surface SOMEWHERE in this lane. Anything outside this set is
 *  `unimplemented-disabled` in every context. Narrowing-only — this cannot enable a stage or invent a
 *  surface, exactly like the stage rail's IMPLEMENTED_GATES. */
const IMPLEMENTED: ReadonlySet<LensKey> = new Set<LensKey>(["calendar", "grid", "list", "overview"]);

/** Per governed gate: the ENABLED lens set (first entry = the gate's default/root lens). These mirror
 *  exactly the projections that already exist — schedule Calendar/Grid/List (#376 VIEW-01) and topic
 *  List/Grid/Overview (#331) — so no new surface is introduced. */
const GATE_ENABLED: Record<LensGate, readonly LensKey[]> = {
  schedule_review: ["calendar", "grid", "list"],
  topic_review: ["list", "grid", "overview"],
};

function asLensGate(gate: string | null | undefined): LensGate | null {
  return gate === "schedule_review" || gate === "topic_review" ? gate : null;
}

/** Does this gate present a lens menu at all? (Scripts and any unmapped gate do not.) */
export function gateHasLensMenu(gate: string | null | undefined): boolean {
  return asLensGate(gate) !== null;
}

/** The gate's default/root lens, or null when the gate has no lens menu. Calendar is the schedule
 *  (and root) default — "Calendar is the active root lens" (Scope §6). */
export function defaultLensFor(gate: string | null | undefined): LensKey | null {
  const g = asLensGate(gate);
  return g ? GATE_ENABLED[g][0] : null;
}

/** The URL key that carries the lens choice for this gate. Schedule projections are remembered
 *  PER RUN (`lens_{roundId}`, #308/#376 — never leaks across runs); the topic lens is the global
 *  `?lens=` (#331). Preserving both keys verbatim is why this is a function, not a constant — the
 *  resolver is still ONE pure function serving both. Returns null when the gate has no lens menu. */
export function lensUrlKey(gate: string | null | undefined, roundId: string | null | undefined): string | null {
  const g = asLensGate(gate);
  if (!g) return null;
  if (g === "schedule_review") return roundId ? `lens_${roundId}` : "lens";
  return "lens";
}

/** Classify a lens for a gate. Pure; the SOLE classifier used for rendering, a11y and URL validation. */
export function classifyLens(gate: string | null | undefined, key: LensKey): LensClass {
  const g = asLensGate(gate);
  if (!IMPLEMENTED.has(key)) return "unimplemented-disabled";
  if (g && GATE_ENABLED[g].includes(key)) return "implemented-enabled";
  return "implemented-context-invalid";
}

function reasonFor(gate: LensGate | null, key: LensKey, cls: LensClass): string | undefined {
  if (cls === "implemented-enabled") return undefined;
  if (cls === "unimplemented-disabled") {
    return key === "analytics"
      ? "Planned for Stage 8 after publication-backed performance evidence is available."
      : "Not built in this transition lane yet.";
  }
  // implemented-context-invalid: real surface, wrong gate.
  const where = key === "calendar"
    ? "The Calendar view belongs to the Coverage / Planning stage."
    : key === "overview"
      ? "The Overview belongs to the Topics stage."
      : `The ${LABEL[key]} view is not available in this stage.`;
  return where;
}

/** The ordered menu entries for a gate, with each entry's class/navigability/reason resolved. Returns
 *  [] when the gate has no lens menu, so the shell renders no menu rather than an empty frame. */
export function lensEntries(gate: string | null | undefined): readonly LensEntry[] {
  const g = asLensGate(gate);
  if (!g) return [];
  return LENS_ORDER.map((key) => {
    const cls = classifyLens(g, key);
    return {
      key,
      label: LABEL[key],
      cls,
      navigable: cls === "implemented-enabled",
      reason: reasonFor(g, key, cls),
    };
  });
}

/** Resolve a raw `?lens=`/`?lens_{roundId}=` value to a real, ENABLED lens for the gate — falling back
 *  to the gate default. Returns null when the gate has no lens menu. Fail-closed by construction:
 *  unknown / unimplemented / context-invalid values never pass, so a stale or cross-gate value cannot
 *  render an invalid view (amendment §B). */
export function resolveLens(gate: string | null | undefined, raw: string | null | undefined): LensKey | null {
  const g = asLensGate(gate);
  if (!g) return null;
  const enabled = GATE_ENABLED[g];
  if (raw && (enabled as readonly string[]).includes(raw)) return raw as LensKey;
  return enabled[0];
}

/** True when a raw URL lens value is NOT the value the resolver would keep — i.e. the shell must
 *  canonicalize the URL (replace + notice). A raw value equal to the resolved lens, or an absent value
 *  on a gate whose default is implied, is NOT stale. Used by the canonicalization effect. */
export function lensNeedsCanonicalization(gate: string | null | undefined, raw: string | null | undefined): boolean {
  const g = asLensGate(gate);
  if (!g) return false;
  if (raw == null || raw === "") return false; // absent → default is implied, no rewrite churn
  return resolveLens(g, raw) !== raw;
}
