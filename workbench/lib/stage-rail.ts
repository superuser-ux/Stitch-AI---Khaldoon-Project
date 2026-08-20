// #355 — the V2 lifecycle stage rail, DERIVED from the active governed workflow version.
//
// WHY THIS REPLACED A LOCAL TABLE. Until #355 the rail was a hand-authored constant listing seven
// invented presentation keys (`coverage|topics|scripts|…`) with hand-written labels and a hand-set
// `active` flag. That is a parallel policy mapping: it can disagree with the governed workflow and
// nothing detects the drift. #354 showed the cost concretely — the rail asserted five stages were
// "not built" while the backend had canonical gates for them, and a reader could not tell whether
// that string described the UI or the domain.
//
// The governed configuration-generation artifact already carries everything a rail needs, versioned
// and auditable: `workflow_version` -> `workflow_stage` rows with `stage_key`, `gate_stage`,
// `enabled`, `stage_label`, `stage_group`, `ordinal`, `generator_kind`, `writer_mode`,
// `generates_from` (gates/engine.py `_workflow_stage_read_model`). So the rail is now a projection
// of that artifact and of nothing else. There is no second source to reconcile.
//
// CANONICAL IDENTIFIERS ONLY. The stage key rendered and put in the URL is the governed `stage_key`
// verbatim (`schedule_review`, `topic_review`, `script_review`, …). V2 derives no display code and
// invents no vocabulary — the same conservation rule the schedule surface follows for `slot_id`.
// Note the seed sets `gate_stage = stage_key` (engine `_workflow_stage_seed_rows`), so
// `scripts -> script_review` is not a mapping V2 authors; it is the artifact's own identity.
//
// FAIL CLOSED. A stage V2 has not built a surface for is rendered visible-but-disabled with the
// governed reason. A stage that is absent from the artifact, disabled in it, or unknown to this
// build is never navigable and never silently coerced to something else.

import type { WorkflowStage, WorkflowVersion } from "./read-model";

/** The GATE STAGES V2 has actually built a surface for.
 *
 *  Keyed by `gate_stage`, NOT by `stage_key`, and that distinction is load-bearing. The governed
 *  payload permits the two to differ: a version may name a stage `scripts_v2` while its canonical
 *  gate is `script_review`. Every API path a surface uses (`/stages/{gate}/state`, the gate
 *  decisions) is addressed by the GATE, so keying on `stage_key` would render a Scripts panel that
 *  talks to the wrong gate — or refuse a correctly-mapped stage merely because its key was renamed.
 *
 *  This is not a policy mapping: it declares which canonical GATES this BUILD can render, and can
 *  only ever narrow what the artifact already authorises. It cannot add, rename, re-order or
 *  re-enable anything — those remain the artifact's to decide. */
const IMPLEMENTED_GATES: Readonly<Record<string, true>> = {
  schedule_review: true,
  topic_review: true,
  script_review: true,
  // R1 Stage 4 — the Final Review surface now exists, so this build can render the canonical
  // `final_review` gate. Adding the entry does NOT make Final Review a stage: it only stops this build
  // from narrowing away a stage the governed artifact already declares and enables. A generation that
  // omits `final_review`, disables it, maps it to a different gate, or maps two enabled stages onto it
  // still yields exactly what it did before — no rail entry, or a visible-but-disabled one carrying the
  // governed reason. Reachability remains a property of the artifact; this set only ever subtracts.
  final_review: true,
};

export type RailStage = {
  /** Governed `stage_key`, carried verbatim. Also the `?stage=` URL value. */
  readonly key: string;
  /** Governed `stage_label`. V2 authors no label of its own. */
  readonly label: string;
  readonly ordinal: number;
  /** Navigable: the artifact enables it AND this build renders it. */
  readonly navigable: boolean;
  /** Truthful, specific reason when not navigable. */
  readonly reason?: string;
  readonly gateStage: string;
  readonly generatorKind: string | null;
  readonly writerMode: string | null;
  readonly generatesFrom: string | null;
};

export type StageRail = {
  readonly stages: readonly RailStage[];
  /** Provenance: which governed generation produced this rail. */
  readonly versionId: string;
  readonly versionNo: number;
  readonly status: string;
};

function railStage(s: WorkflowStage, ambiguousGates: ReadonlySet<string>): RailStage {
  // The governed mapping is CONSUMED here: the gate decides what can render, not the stage key.
  const gate = typeof s.gate_stage === "string" ? s.gate_stage : "";
  const built = gate.length > 0 && IMPLEMENTED_GATES[gate] === true;
  const ambiguous = gate.length > 0 && ambiguousGates.has(gate);
  const navigable = Boolean(s.enabled) && built && !ambiguous;
  return {
    key: s.stage_key,
    label: s.stage_label,
    ordinal: s.ordinal,
    navigable,
    reason: navigable
      ? undefined
      : !s.enabled
        ? "Disabled in the active governed workflow version."
        : ambiguous
          ? "Two governed stages map to the same gate; the mapping is ambiguous, so this stage is not offered."
          : gate.length === 0
            ? "The governed version declares no gate for this stage."
            : "No workbench surface is built for this governed stage's gate yet.",
    gateStage: gate,
    generatorKind: s.generator_kind ?? null,
    writerMode: s.writer_mode ?? null,
    generatesFrom: s.generates_from ?? null,
  };
}

/** Project the governed version onto the rail. Returns null when the artifact cannot be used —
 *  the caller then renders a truthful unavailable state rather than an invented rail. */
export function deriveStageRail(version: WorkflowVersion | null | undefined): StageRail | null {
  if (!version || !Array.isArray(version.stages) || version.stages.length === 0) return null;
  if (!version.version_id) return null;
  const usable = [...version.stages]
    .filter((s) => typeof s?.stage_key === "string" && s.stage_key.length > 0);
  // A gate claimed by more than one ENABLED stage is ambiguous: V2 cannot know which one a
  // gate-addressed read belongs to, so it offers neither rather than picking one.
  const seen = new Map<string, number>();
  for (const s of usable) {
    if (!s.enabled || typeof s.gate_stage !== "string" || !s.gate_stage) continue;
    seen.set(s.gate_stage, (seen.get(s.gate_stage) ?? 0) + 1);
  }
  const ambiguousGates = new Set([...seen.entries()].filter(([, n]) => n > 1).map(([g]) => g));
  const stages = usable
    .sort((a, b) => a.ordinal - b.ordinal || a.stage_key.localeCompare(b.stage_key))
    .map((s) => railStage(s, ambiguousGates));
  if (stages.length === 0) return null;
  return {
    stages,
    versionId: version.version_id,
    versionNo: version.version_no,
    status: version.status,
  };
}

/** Resolve a `?stage=` value against the DERIVED rail.
 *
 *  Fail-closed by construction: an unknown, absent, disabled or unbuilt stage falls back to the
 *  first navigable stage rather than rendering a surface the artifact did not authorise. Returns
 *  null when nothing is navigable — the caller must then say so, not guess. */
export function resolveRailStage(rail: StageRail | null, raw: string | null | undefined): RailStage | null {
  if (!rail) return null;
  const navigable = rail.stages.filter((s) => s.navigable);
  if (navigable.length === 0) return null;
  return navigable.find((s) => s.key === raw) ?? navigable[0];
}
