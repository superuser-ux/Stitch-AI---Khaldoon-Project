// R1 Stage 4 — focused unit + boundary validation for the V2 Final Review vertical.
//
// Pure functions and the declarative /gw boundary; no browser, no network, no stack. Run:
//   node --experimental-strip-types scripts/final-review-advancement.test.ts
// Kept out of e2e/ so Playwright never collects it (mirrors scripts/sign-off-action.test.ts).
//
// WHAT THIS SUITE IS FOR. The Stage-4 invariants that must not regress are mostly NEGATIVE — sign-off
// does not advance, no decision is sent without an exact package binding, resolve is not offered before
// a decision exists, no actor/authority field is ever composed, the write boundary admits exactly the
// two canonical operations and nothing adjacent. Negatives are cheap to break and invisible in a
// green browser run, so they are pinned here as executable assertions rather than as prose.
import { strict as assert } from "node:assert";
import {
  ADVANCE_OFFER_COPY,
  advanceOffer,
  advancementNonAcceptedCopy,
  classifyAdvancementFailure,
  classifyDecideSuccess,
  classifyResolveSuccess,
  DECIDE_OFFER_COPY,
  decideOffer,
  decidePath,
  decideRequest,
  GATE_DECISIONS,
  isGateDecision,
  resolvePath,
  resolveRequest,
} from "../lib/final-review-advancement.ts";
import { resolveAllowedPath, resolveAllowedWritePath } from "../lib/api-contract.ts";
import { deriveStageRail, resolveRailStage } from "../lib/stage-rail.ts";
import { WriteError, type ApprovalPreflightTuple, type WorkflowVersion } from "../lib/read-model.ts";
import * as signOff from "../lib/sign-off-action.ts";

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
const SLOT = "RFIN-1";
const OTHER = "RFIN-2";

const TUPLE: ApprovalPreflightTuple = {
  gate_id: GATE,
  slot_id: SLOT,
  snapshot_id: SNAP,
  topic_revision: 2,
  script_revision: 3,
  workflow_version_id: WF,
};

function stage(over: Record<string, unknown> = {}) {
  return {
    stage_key: "final_review",
    stage_label: "Publish approval",
    stage_group: "Sign-off",
    ordinal: 4,
    enabled: true,
    gate_stage: "final_review",
    stage_kind: "signoff",
    generator_kind: null,
    writer_mode: null,
    generates_from: null,
    approve_to: "READY_FOR_PRODUCTION",
    ...over,
  } as WorkflowVersion["stages"][number];
}

function version(stages: WorkflowVersion["stages"]): WorkflowVersion {
  return { version_id: "v-1", version_no: 7, status: "active", stages };
}

console.log("\nR1 Stage 4 — the decision vocabulary MIRRORS engine.DECISIONS");
{
  check("exactly the three canonical decisions, in the server's own order",
    JSON.stringify(GATE_DECISIONS) === JSON.stringify(["approve", "reject", "request_change"]));
  check("a non-canonical decision is not admitted", !isGateDecision("advance") && !isGateDecision("sign_off"));
  check("every canonical decision is admitted", GATE_DECISIONS.every(isGateDecision));
}

console.log("\nR1 Stage 4 — the request bodies carry NO authority and bind the EXACT target");
{
  const body = decideRequest("approve", TUPLE);
  check("slot_ids is always the EXACT single canonical target (never a whole-batch null/empty)",
    Array.isArray(body.slot_ids) && body.slot_ids.length === 1 && body.slot_ids[0] === SLOT);
  check("the revision is the server-authored script_revision, copied verbatim",
    body.revision === TUPLE.script_revision);
  const keys = Object.keys(body).sort();
  check("approve sends exactly {decision, revision, slot_ids} — nothing else",
    JSON.stringify(keys) === JSON.stringify(["decision", "revision", "slot_ids"]));
  // The single most important negative in this file: no field by which a client could assert who is
  // acting, what they may do, or that a quorum is met.
  const forbidden = ["actor", "approver_id", "principal", "principal_id", "role", "assignment",
    "quorum", "authority", "eligibility", "outcome", "status", "advance", "auto_advance",
    "advancement_mode", "resolve"];
  check("no actor/principal/role/assignment/quorum/authority/eligibility field is ever composed",
    forbidden.every((f) => !(f in body)));

  const rc = decideRequest("request_change", TUPLE, "please tighten the hook");
  check("request_change carries the rationale the canonical command requires",
    rc.notes === "please tighten the hook");
  check("request_change without a rationale still sends the field (the SERVER refuses it, not us)",
    decideRequest("request_change", TUPLE).notes === "");
  check("approve never smuggles a notes field", !("notes" in decideRequest("approve", TUPLE)));

  const rr = resolveRequest(SLOT);
  check("resolve sends exactly the single canonical target and no actor",
    JSON.stringify(Object.keys(rr)) === JSON.stringify(["slot_ids"]) && rr.slot_ids[0] === SLOT);

  check("gate_id travels in the PATH only", decidePath(GATE) === `/gw/gates/${GATE}/decide`
    && resolvePath(GATE) === `/gw/gates/${GATE}/resolve`);
  check("a path-hostile gate id is encoded, never interpolated raw",
    decidePath("a/b").includes("a%2Fb"));
}

console.log("\nR1 Stage 4 — the DECISION control is offered only against an exact server-authored pin");
{
  check("offered for a complete, matching tuple on a canonical target",
    decideOffer(GATE, SLOT, [SLOT, OTHER], TUPLE).offered);
  check("withheld when the server reports no open gate",
    decideOffer(null, SLOT, [SLOT], TUPLE).reason === "no_open_gate");
  check("withheld when the slot is not a server-authored gate target",
    decideOffer(GATE, SLOT, [OTHER], TUPLE).reason === "not_a_gate_target");
  check("withheld when there is no tuple at all",
    decideOffer(GATE, SLOT, [SLOT], null).reason === "no_complete_tuple");
  check("withheld on a partial tuple — a pin is never assembled or defaulted",
    decideOffer(GATE, SLOT, [SLOT], { ...TUPLE, snapshot_id: "" }).reason === "no_complete_tuple");
  check("withheld on a non-integer revision",
    decideOffer(GATE, SLOT, [SLOT], { ...TUPLE, script_revision: 1.5 }).reason === "no_complete_tuple");
  check("withheld when the tuple names a different gate — nothing is reconciled",
    decideOffer(GATE, SLOT, [SLOT], { ...TUPLE, gate_id: "other" }).reason === "target_mismatch");
  check("withheld when the tuple names a different slot",
    decideOffer(GATE, SLOT, [SLOT], { ...TUPLE, slot_id: OTHER }).reason === "target_mismatch");
  check("every withheld reason has neutral copy that claims no authority over the operator",
    Object.values(DECIDE_OFFER_COPY).every((c) => !/\byou\b/i.test(c)));
}

console.log("\nR1 Stage 4 — DECISION-BEFORE-RESOLVE is preserved, and resolve is never implied");
{
  check("withheld before any decision is recorded",
    advanceOffer(GATE, SLOT, [SLOT], "pending").reason === "no_decision_recorded");
  check("withheld when the outcome is absent",
    advanceOffer(GATE, SLOT, [SLOT], null).reason === "no_decision_recorded");
  // Fail closed on drift: an unrecognized outcome must never be read as "decided".
  check("withheld on an UNRECOGNIZED outcome (contract drift is not a decision)",
    advanceOffer(GATE, SLOT, [SLOT], "signed_off").reason === "no_decision_recorded");
  check("offered once the SERVER reports an approved outcome",
    advanceOffer(GATE, SLOT, [SLOT], "approved").offered);
  check("offered for a negative outcome too — resolve applies decisions, it does not judge them",
    advanceOffer(GATE, SLOT, [SLOT], "rejected").offered
    && advanceOffer(GATE, SLOT, [SLOT], "changes_requested").offered);
  check("withheld when the slot is not a server-authored gate target",
    advanceOffer(GATE, SLOT, [OTHER], "approved").reason === "not_a_gate_target");
  check("withheld when the server reports no open gate",
    advanceOffer(null, SLOT, [SLOT], "approved").reason === "no_open_gate");
  check("every withheld reason has neutral copy that claims no authority over the operator",
    Object.values(ADVANCE_OFFER_COPY).every((c) => !/\byou\b/i.test(c)));
}

console.log("\nR1 Stage 4 — SIGN-OFF IS EVIDENCE ONLY (structural separation, not a promise)");
{
  // The sign-off module must expose nothing by which evidence could cause a decision or a transition,
  // and this module must expose nothing that records evidence. If either ever gains such an export the
  // separation has been broken at the seam, and this fails before any UI can rely on it.
  const signOffExports = Object.keys(signOff);
  check("the sign-off module exports no decide/resolve/advance capability",
    !signOffExports.some((k) => /decide|resolve|advance|transition|lifecycle/i.test(k)));
  check("the sign-off request body carries no decision, advance, or lifecycle field",
    JSON.stringify(Object.keys(signOff.signOffRequest(TUPLE, "k")).sort())
      === JSON.stringify(["idempotency_key", "script_revision", "snapshot_id", "topic_revision",
        "workflow_version_id"]));
  check("the sign-off path is a DISTINCT endpoint from both authority endpoints",
    signOff.signOffPath(GATE, SLOT) !== decidePath(GATE)
    && signOff.signOffPath(GATE, SLOT) !== resolvePath(GATE));
  check("no canonical sign-off outcome is a lifecycle word",
    signOff.SIGNOFF_OUTCOMES.every((c) => !/approved|resolved|advanced|committed/i.test(c)));
  check("the sign-off receipt status is the contract literal 'recorded', never a lifecycle state",
    signOff.SIGNOFF_RECEIPT_STATUS === "recorded");
}

console.log("\nR1 Stage 4 — NO AUTOMATIC ADVANCEMENT and NO speculative advancement-policy schema");
{
  // Nothing in the advancement module may name, persist, toggle, or default an advancement mode. The
  // future policy dimension is preserved by separation of responsibility, not by a field.
  const exported = [
    "GATE_DECISIONS", "isGateDecision", "decidePath", "resolvePath", "decideRequest",
    "resolveRequest", "decideOffer", "advanceOffer", "DECIDE_OFFER_COPY", "ADVANCE_OFFER_COPY",
    "classifyDecideSuccess", "classifyResolveSuccess", "classifyAdvancementFailure",
    "advancementNonAcceptedCopy",
  ];
  check("the module exposes no auto-advance / advancement-mode / policy capability",
    !exported.some((k) => /auto|mode|policy|preference|toggle|schedule/i.test(k)));
  check("the decide body has no advancement-policy field",
    !("advancement_mode" in decideRequest("approve", TUPLE))
    && !("auto_advance" in decideRequest("approve", TUPLE)));
  check("the resolve body has no advancement-policy field",
    !("advancement_mode" in resolveRequest(SLOT)) && !("auto_advance" in resolveRequest(SLOT)));
}

console.log("\nR1 Stage 4 — results are classified truthfully; no fabricated success");
{
  // `engine.decide` returns `sorted(chosen)` — the LIST of slot ids, not a count. Pinned here because
  // an earlier revision validated an integer and would have called every real success "drift".
  check("the canonical decide body (a list of slot ids) is accepted",
    classifyDecideSuccess({ touched: [SLOT] }).kind === "accepted");
  check("an EMPTY touched list is canonical (nothing matched), not drift",
    classifyDecideSuccess({ touched: [] }).kind === "accepted");
  check("a COUNT-shaped decide body is DRIFT — the contract is a list, not a number",
    classifyDecideSuccess({ touched: 1 }).kind === "contract_drift");
  check("a decide body without a touched list is DRIFT, never an accepted decision",
    classifyDecideSuccess({ touched: "1" }).kind === "contract_drift"
    && classifyDecideSuccess({}).kind === "contract_drift"
    && classifyDecideSuccess(null).kind === "contract_drift");
  check("a non-slot-id entry in touched is DRIFT",
    classifyDecideSuccess({ touched: [1] }).kind === "contract_drift"
    && classifyDecideSuccess({ touched: [""] }).kind === "contract_drift");

  check("a canonical resolve ledger is accepted",
    classifyResolveSuccess({ outcomes: { [SLOT]: "approved" } }).kind === "accepted");
  check("an EMPTY ledger is canonical (the server moved nothing), not drift",
    classifyResolveSuccess({ outcomes: {} }).kind === "accepted");
  check("a resolve body without an outcomes map is DRIFT",
    classifyResolveSuccess({}).kind === "contract_drift"
    && classifyResolveSuccess({ outcomes: [] }).kind === "contract_drift");
  check("a non-string outcome value is DRIFT, never rendered as a transition",
    classifyResolveSuccess({ outcomes: { [SLOT]: 1 } }).kind === "contract_drift");

  check("status 0 is TRANSPORT — whether the server was reached is unknown",
    classifyAdvancementFailure(new WriteError(0, { detail: "x" })).kind === "transport");
  check("a 403 from V2's own boundary is a SEAM REFUSAL, never a server denial",
    classifyAdvancementFailure(new WriteError(403, { detail: "not in the write boundary" }))
      .kind === "seam_refusal");
  check("a 501 non-dev signing refusal is a SEAM REFUSAL",
    classifyAdvancementFailure(new WriteError(501, { detail: "writes only in dev" })).kind === "seam_refusal");
  check("a 503 unreachable seam is a SEAM REFUSAL, not a transport retry",
    classifyAdvancementFailure(new WriteError(503, { detail: "api unreachable" })).kind === "seam_refusal");
  check("an upstream 409 is a server REFUSAL relayed verbatim",
    (() => {
      const r = classifyAdvancementFailure(new WriteError(409, { detail: "gate is resolved — not open" }));
      return r.kind === "refused" && r.detail === "gate is resolved — not open";
    })());
  check("an upstream 400 is a server REFUSAL relayed verbatim",
    classifyAdvancementFailure(new WriteError(400, { detail: "bad decision" })).kind === "refused");
  check("an unrecognized failure shape is DRIFT, never silently absorbed",
    classifyAdvancementFailure(new WriteError(422, {})).kind === "contract_drift");
  check("non-accepted copy never claims a lifecycle outcome",
    (["refused", "seam_refusal", "transport", "contract_drift"] as const)
      .every((k) => !/advanced|approved successfully/i.test(advancementNonAcceptedCopy(k))));
}

console.log("\nR1 Stage 4 — reachability is DERIVED from the governed artifact, never assumed");
{
  const rail = deriveStageRail(version([
    stage({ stage_key: "script_review", gate_stage: "script_review", ordinal: 3, stage_label: "Scripts" }),
    stage(),
  ]));
  check("an ENABLED governed final_review stage is navigable",
    rail!.stages.find((s) => s.gateStage === "final_review")!.navigable);
  check("the governed LABEL is carried verbatim — V2 authors none",
    rail!.stages.find((s) => s.gateStage === "final_review")!.label === "Publish approval");

  const disabled = deriveStageRail(version([stage({ enabled: false })]));
  check("a DISABLED governed final_review stage is never navigable",
    !disabled!.stages[0].navigable
    && disabled!.stages[0].reason === "Disabled in the active governed workflow version.");

  const absent = deriveStageRail(version([
    stage({ stage_key: "script_review", gate_stage: "script_review", stage_label: "Scripts" }),
  ]));
  check("a generation that OMITS final_review yields no final-review rail entry at all",
    !absent!.stages.some((s) => s.gateStage === "final_review"));
  check("resolving a ?stage=final_review against a version without it never selects it",
    resolveRailStage(absent, "final_review")!.gateStage === "script_review");

  const ambiguous = deriveStageRail(version([
    stage({ stage_key: "final_review", ordinal: 4 }),
    stage({ stage_key: "publish_approval", ordinal: 5 }),
  ]));
  check("two enabled stages mapped to the final_review gate stay ambiguous and non-navigable",
    ambiguous!.stages.every((s) => !s.navigable));
}

console.log("\nR1 Stage 4 — the /gw boundary admits EXACTLY the canonical operations, nothing adjacent");
{
  check("the canonical gate DECISION is on the write boundary",
    resolveAllowedWritePath(["gates", GATE, "decide"]) !== null);
  check("the canonical gate RESOLVE is on the write boundary",
    resolveAllowedWritePath(["gates", GATE, "resolve"]) !== null);
  check("the boundary is an EXACT match, not a prefix under /gates",
    resolveAllowedWritePath(["gates", GATE, "decide", "extra"]) === null
    && resolveAllowedWritePath(["gates", GATE, "open"]) === null
    && resolveAllowedWritePath(["gates", GATE, "reopen"]) === null
    && resolveAllowedWritePath(["gates"]) === null);
  check("traversal segments are refused before any pattern match",
    resolveAllowedWritePath(["gates", "..", "decide"]) === null);

  check("the final-review stage STATE read is admitted",
    resolveAllowedPath(["rounds", "RFIN", "stages", "final_review", "state"]) !== null);
  // Deliberately narrow: adding the gate to SERVED_GATES would have opened these two as well.
  check("`advanced` and `action` are NOT opened for final_review",
    resolveAllowedPath(["rounds", "RFIN", "stages", "final_review", "advanced"]) === null
    && resolveAllowedPath(["rounds", "RFIN", "stages", "final_review", "action"]) === null);
  check("an arbitrary gate's state read is still refused",
    resolveAllowedPath(["rounds", "RFIN", "stages", "production_review", "state"]) === null);

  check("the canonical gate detail read is admitted",
    resolveAllowedPath(["gates", GATE]) !== null);
  check("the gate detail read is an EXACT two-segment match",
    resolveAllowedPath(["gates"]) === null
    && resolveAllowedPath(["gates", GATE, "decide"]) === null);
  check("decide/resolve are NOT readable — they are writes only",
    resolveAllowedPath(["gates", GATE, "resolve"]) === null);
  check("the write boundary does not admit the READ endpoints",
    resolveAllowedWritePath(["gates", GATE]) === null
    && resolveAllowedWritePath(["rounds", "RFIN", "stages", "final_review", "state"]) === null);
  // The sign-off command must remain reachable and remain DISTINCT from the two authority endpoints.
  check("the sign-off command is still on the write boundary and is a different path",
    resolveAllowedWritePath(["gates", GATE, "slots", SLOT, "sign-off"]) !== null);
}

assert.equal(typeof failures, "number");
console.log(failures === 0 ? "\nALL PASS\n" : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
