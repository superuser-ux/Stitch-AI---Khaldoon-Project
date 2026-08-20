// #447 — focused unit + type validation for the approval-preflight presentation mapping.
// Pure functions; no browser, no network, no stack. Run:
//   node --experimental-strip-types scripts/approval-preflight-presentation.test.ts
// Kept out of e2e/ so Playwright never collects it (mirrors scripts/final-review-presentation.test.ts).
import { strict as assert } from "node:assert";
import {
  humanAuthorityCopy,
  preflightVerdict,
  TUPLE_MEMBER_ORDER,
  tuplePresentation,
} from "../lib/approval-preflight-presentation.ts";
import type { ApprovalPreflight, ApprovalPreflightTuple } from "../lib/read-model.ts";

let failures = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`  [PASS] ${name}`);
  else {
    failures += 1;
    console.log(`  [FAIL] ${name}`);
  }
}

const GATE = "11111111-1111-1111-1111-111111111111";
const SNAP = "22222222-2222-2222-2222-222222222222";
const WF = "33333333-3333-3333-3333-333333333333";

const TUPLE: ApprovalPreflightTuple = {
  gate_id: GATE,
  slot_id: "S1",
  snapshot_id: SNAP,
  topic_revision: 2,
  script_revision: 3,
  workflow_version_id: WF,
};

function model(over: Partial<ApprovalPreflight> = {}): ApprovalPreflight {
  return {
    gate_id: GATE,
    slot_id: "S1",
    available: true,
    status: "recorded",
    reason_code: "coherent",
    detail: "display only",
    target_identity: {
      gate_id: GATE,
      slot_id: "S1",
      gate_stage: "final_review",
      gate_status: "open",
      admitted: true,
    },
    package: null,
    target_package_tuple: TUPLE,
    evidence: {
      workflow: { pinned: { version_id: WF, source: "script_provenance" }, active: { version_id: WF }, divergent: false },
      final_review: {
        stage: "final_review",
        actor_model_enabled: true,
        hard_floor_stage: true,
        human_signoff_required: true,
        source: "actor_model_hard_floor",
        authorization_evaluated: false,
      },
      present_state: { gate_status: "open", outcome: "approved", governed_head: { topic: 2, script: 3 } },
      production_direction: { pinned: { present: false }, observed: { present: false }, status: "not_yet_recorded" },
      classifications: {
        agent_execution: "not_applicable",
        agent_rep_delegation: "not_recorded",
        provider_operation: "not_applicable",
        secret_authority: "not_applicable",
      },
    },
    denials: [],
    ...over,
  };
}

// Copy must never read as permission, an action offer, or an approval outcome.
const FORBIDDEN = [
  "you may",
  "you can",
  "your approval",
  "awaiting your",
  "authorized",
  "authorised",
  "permitted",
  "click",
  "approve now",
  "sign off now",
];
function noForbidden(copy: string): boolean {
  const c = copy.toLowerCase();
  return FORBIDDEN.every((f) => !c.includes(f));
}

console.log("#447 approval-preflight presentation");

// 1 — the four categories are derived from the authoritative fields, never collapsed.
check("coherent -> category coherent, no primary reason", (() => {
  const v = preflightVerdict(model());
  return v.category === "coherent" && v.primaryReason === null;
})());

check("recorded history + not available -> not_eligible (NEVER coherent, NEVER unknown_history)", (() => {
  const v = preflightVerdict(model({ available: false, reason_code: "signoff_blocked" }));
  return v.category === "not_eligible" && v.primaryReason === "signoff_blocked";
})());

check("unknown_history wins over the availability flag", (() => {
  const v = preflightVerdict(
    model({ status: "unknown_history", available: false, reason_code: "missing_target_package_snapshot" }),
  );
  return v.category === "unknown_history" && v.primaryReason === "missing_target_package_snapshot";
})());

check("unavailable wins over the availability flag", (() => {
  const v = preflightVerdict(
    model({ status: "unavailable", available: false, reason_code: "not_a_final_review_target" }),
  );
  return v.category === "unavailable" && v.primaryReason === "not_a_final_review_target";
})());

// 2 — the primary reason is the server's verbatim `reason_code`; denials are never re-ranked.
check("primary reason is taken verbatim, never re-derived from denials order", (() => {
  const v = preflightVerdict(
    model({
      available: false,
      reason_code: "signoff_stale",
      denials: [
        { code: "signoff_stale", detail: "a" },
        { code: "production_direction_mismatch", detail: "b" },
      ],
    }),
  );
  return v.primaryReason === "signoff_stale";
})());

// 3 — no copy anywhere reads as permission or an action offer.
check("no verdict copy implies permission or an action", (() => {
  const cats: ApprovalPreflight[] = [
    model(),
    model({ available: false, reason_code: "signoff_blocked" }),
    model({ status: "unknown_history", available: false }),
    model({ status: "unavailable", available: false }),
  ];
  return cats.every((m) => noForbidden(preflightVerdict(m).copy));
})());

check("human-authority copy states a STAGE requirement, never a principal's permission", (() => {
  const required = humanAuthorityCopy(model().evidence.final_review);
  const notRequired = humanAuthorityCopy(
    model({
      evidence: { ...model().evidence, final_review: { ...model().evidence.final_review!, human_signoff_required: false } },
    }).evidence.final_review,
  );
  return (
    noForbidden(required) &&
    noForbidden(notRequired) &&
    required.includes("No principal has been evaluated") &&
    notRequired.includes("No principal has been evaluated")
  );
})());

check("absent final-review evidence yields neutral copy, never an assumed floor", (() => {
  const c = humanAuthorityCopy(null);
  return noForbidden(c) && !c.toLowerCase().includes("requires human sign-off");
})());

// 4 — the six-member tuple is all-or-nothing.
check("complete tuple presents all six members in canonical order", (() => {
  const t = tuplePresentation(TUPLE);
  return (
    t.complete &&
    t.members !== null &&
    t.members.length === 6 &&
    t.members.map((m) => m.key).join(",") === TUPLE_MEMBER_ORDER.join(",")
  );
})());

check("withheld tuple (null) is never presentable", (() => {
  const t = tuplePresentation(null);
  return t.complete === false && t.members === null;
})());

for (const key of TUPLE_MEMBER_ORDER) {
  check(`missing member ${key} -> refuses to present a PARTIAL tuple`, (() => {
    const partial = { ...TUPLE } as Record<string, unknown>;
    delete partial[key];
    const t = tuplePresentation(partial as unknown as ApprovalPreflightTuple);
    return t.complete === false && t.members === null;
  })());

  check(`null member ${key} -> refuses to present a PARTIAL tuple`, (() => {
    const partial = { ...TUPLE, [key]: null } as unknown as ApprovalPreflightTuple;
    const t = tuplePresentation(partial);
    return t.complete === false && t.members === null;
  })());
}

check("blank member -> refuses to present, and is never padded or defaulted", (() => {
  const t = tuplePresentation({ ...TUPLE, snapshot_id: "   " });
  return t.complete === false && t.members === null;
})());

check("revision 0 is a real value and is NOT treated as missing", (() => {
  const t = tuplePresentation({ ...TUPLE, topic_revision: 0 });
  return t.complete === true && t.members !== null && t.members[3].value === "0";
})());

// 5 — values are rendered verbatim.
check("values are stringified verbatim, never abbreviated or substituted", (() => {
  const t = tuplePresentation(TUPLE);
  return t.complete && t.members !== null && t.members[2].value === SNAP && t.members[5].value === WF;
})());

assert.equal(typeof preflightVerdict, "function");
console.log(failures === 0 ? "ALL PASS" : `FAILURES: ${failures}`);
process.exit(failures === 0 ? 0 : 1);
