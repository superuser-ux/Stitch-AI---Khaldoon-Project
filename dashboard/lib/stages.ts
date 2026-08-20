// #39 — Stage identity model (Option 4: alias layer).
//
// The CANONICAL identity of a workflow stage is its gate id (e.g. "final_review"). It is stable and
// persisted (gate.stage, gate_decision, engine transitions) and is NEVER renamed here — renaming it
// would be a data migration. Operator-facing labels are presentation metadata that may change freely
// without touching identity. This module is the single dashboard-side source for stage display labels,
// alias resolution (dashboard short key <-> canonical gate id), and a stable debug identity.
//
// Editable-at-runtime labels (admin-managed via workflow_stage.stage_label) are FUTURE #6 scope; until
// the seeding/source-of-truth ambiguity is resolved, these labels are the static dashboard defaults —
// not a runtime source of truth.

export type StageIdentity = {
  canonicalGate: string;      // persisted, immutable identity — e.g. "final_review"
  aliasKey: string;           // dashboard short key used in STAGES/testids/views.ts — e.g. "final"
  label: string;              // preferred operator-facing label (presentation only)
  meaning: string;            // what the stage actually is (glossary + debug clarity)
  group: string;
  slotStatus: string | null;  // resulting slot.status for this stage, if applicable
  inReviewNav: boolean;       // surfaced in the dashboard review nav today (vs engine-native only)
};

// Ordered by the canonical engine pipeline. Labels are the ONLY mutable field; canonicalGate is identity.
export const STAGE_IDENTITY: StageIdentity[] = [
  { canonicalGate: "schedule_review",     aliasKey: "schedule",     label: "Schedule",                meaning: "schedule / slot-reservation review",                         group: "Content",    slotStatus: "RESERVED",             inReviewNav: true },
  { canonicalGate: "topic_review",        aliasKey: "topic",        label: "Topics",                  meaning: "topic-title review",                                        group: "Content",    slotStatus: "TOPIC_PROPOSED",       inReviewNav: true },
  { canonicalGate: "script_review",       aliasKey: "script",       label: "Scripts",                 meaning: "script-draft review",                                       group: "Content",    slotStatus: "DRAFT_ASSIGNED",       inReviewNav: true },
  { canonicalGate: "native_review",       aliasKey: "native",       label: "Language sign-off",       meaning: "dialect / language sign-off (engine-native; not in review nav yet)", group: "Sign-off",  slotStatus: null,                   inReviewNav: false },
  { canonicalGate: "scholar_review",      aliasKey: "scholar",      label: "Religious sign-off",      meaning: "religious / scholarly sign-off (engine-native; not in review nav yet)", group: "Sign-off", slotStatus: null,                inReviewNav: false },
  { canonicalGate: "final_review",        aliasKey: "final",        label: "Pre Production Approval", meaning: "pre-production sign-off (NOT publishing — the label 'Publish approval' was misleading)", group: "Sign-off", slotStatus: "APPROVED_ASSIGNED", inReviewNav: true },
  { canonicalGate: "production_review",   aliasKey: "production",   label: "Production",              meaning: "production-readiness review",                                group: "Production", slotStatus: "READY_FOR_PRODUCTION", inReviewNav: true },
  { canonicalGate: "edit_review",         aliasKey: "edit",         label: "Media edit",              meaning: "media-edit review",                                          group: "Production", slotStatus: "PRODUCED",             inReviewNav: true },
  { canonicalGate: "distribution_review", aliasKey: "distribution", label: "Distribution",            meaning: "distribution / posting review",                              group: "Production", slotStatus: "EDITED",               inReviewNav: true },
];

const BY_GATE = new Map(STAGE_IDENTITY.map((s) => [s.canonicalGate, s]));
const BY_ALIAS = new Map(STAGE_IDENTITY.map((s) => [s.aliasKey, s]));

// resolve either a dashboard alias key ("final") OR a canonical gate id ("final_review") to its record
export function stageIdentity(keyOrGate: string): StageIdentity | undefined {
  return BY_ALIAS.get(keyOrGate) ?? BY_GATE.get(keyOrGate);
}

// the canonical (persisted) gate id for a dashboard alias key — identity resolution, never renamed
export function canonicalGate(keyOrGate: string): string {
  return stageIdentity(keyOrGate)?.canonicalGate ?? keyOrGate;
}

// the preferred operator-facing label — presentation only; safe to change without touching identity
export function stageLabel(keyOrGate: string): string {
  return stageIdentity(keyOrGate)?.label ?? keyOrGate;
}

// a stable debug identity for logs/troubleshooting — always the canonical gate + alias, never the label
export function stageDebugId(keyOrGate: string): string {
  const s = stageIdentity(keyOrGate);
  return s ? `${s.canonicalGate}(${s.aliasKey})` : keyOrGate;
}
