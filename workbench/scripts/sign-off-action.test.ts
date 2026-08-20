// #449 — focused unit + type validation for the V2 sign-off action logic.
// Pure functions; no browser, no network, no stack. Run:
//   node --experimental-strip-types scripts/sign-off-action.test.ts
// Kept out of e2e/ so Playwright never collects it (mirrors scripts/approval-preflight-presentation.test.ts).
import { strict as assert } from "node:assert";
import {
  ATTEMPTABILITY_COPY,
  attemptability,
  classifyFailure,
  classifySuccess,
  isCanonicalOutcome,
  isRetryable,
  nonOutcomeCopy,
  OUTCOME_COPY,
  RECEIPT_MEMBERS,
  SIGNOFF_OPERATION,
  SIGNOFF_OUTCOMES,
  SIGNOFF_RECEIPT_STATUS,
  signOffPath,
  signOffRequest,
  tupleIdentity,
} from "../lib/sign-off-action.ts";
import {
  WriteError,
  type ApprovalPreflight,
  type ApprovalPreflightTuple,
} from "../lib/read-model.ts";

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
const SLOT = "S1";

const TUPLE: ApprovalPreflightTuple = {
  gate_id: GATE,
  slot_id: SLOT,
  snapshot_id: SNAP,
  topic_revision: 2,
  script_revision: 3,
  workflow_version_id: WF,
};

function model(over: Partial<ApprovalPreflight> = {}): ApprovalPreflight {
  return {
    gate_id: GATE,
    slot_id: SLOT,
    available: true,
    status: "recorded",
    reason_code: "coherent",
    detail: "display only",
    target_identity: { gate_id: GATE, slot_id: SLOT, gate_stage: "final_review", gate_status: "open", admitted: true },
    package: null,
    target_package_tuple: TUPLE,
    evidence: {
      workflow: { pinned: null, active: null, divergent: null },
      final_review: null,
      present_state: null,
      production_direction: null,
      classifications: {
        agent_execution: "none",
        agent_rep_delegation: "none",
        provider_operation: "none",
        secret_authority: "none",
      },
    },
    denials: [],
    ...over,
  } as ApprovalPreflight;
}

/** The exact FastAPI/gate-API error envelope, as `postJson` unwraps it. */
function serverError(status: number, code: string): WriteError {
  return new WriteError(status, { error: code });
}
/** The exact /gw seam refusal envelope: a PROSE string under `detail`. */
function seamError(status: number, detail: string): WriteError {
  return new WriteError(status, { detail });
}

console.log("\n#449 — canonical vocabulary is bound to the merged #440 contract");
{
  // The single place a #440 drift can be caught. If engine.SIGNOFF_ERROR_STATUS changes, this fails
  // loudly instead of the surface silently rendering the new code as unrecognized drift.
  const expected = [
    "signoff_unauthenticated", "signoff_not_authorized", "signoff_hard_floor",
    "signoff_target_unavailable", "signoff_package_mismatch", "signoff_blocked", "signoff_stale",
    "signoff_already_recorded", "idempotency_key_mismatch", "signoff_conflict", "invalid_request",
  ];
  check("exactly 11 canonical outcomes", SIGNOFF_OUTCOMES.length === 11);
  check("vocabulary matches engine.SIGNOFF_ERROR_STATUS exactly",
    JSON.stringify([...SIGNOFF_OUTCOMES].sort()) === JSON.stringify([...expected].sort()));
  check("every canonical code has neutral copy",
    SIGNOFF_OUTCOMES.every((c) => typeof OUTCOME_COPY[c] === "string" && OUTCOME_COPY[c].length > 20));
  check("copy map adds no code beyond the canonical set",
    Object.keys(OUTCOME_COPY).length === SIGNOFF_OUTCOMES.length);
  check("isCanonicalOutcome accepts a canonical code", isCanonicalOutcome("signoff_stale"));
  check("isCanonicalOutcome rejects an invented code", !isCanonicalOutcome("signoff_probably_fine"));
  check("isCanonicalOutcome rejects non-strings", !isCanonicalOutcome(undefined) && !isCanonicalOutcome(7));
}

console.log("\n#449 — the request carries exactly five fields, forwarded verbatim");
{
  const req = signOffRequest(TUPLE, "key-abc");
  check("exactly five keys", Object.keys(req).length === 5);
  check("no gate_id / slot_id in the body (route parameters only)",
    !("gate_id" in req) && !("slot_id" in req));
  const forbidden = ["actor", "principal", "role", "authority", "package", "generation",
    "eligibility", "approver_id", "outcome", "available"];
  check("no actor/principal/role/authority/eligibility field",
    forbidden.every((k) => !(k in (req as Record<string, unknown>))));
  check("snapshot_id verbatim", req.snapshot_id === SNAP);
  check("workflow_version_id verbatim", req.workflow_version_id === WF);
  check("topic_revision verbatim (number, not re-parsed)", req.topic_revision === 2);
  check("script_revision verbatim (number, not re-parsed)", req.script_revision === 3);
  check("idempotency_key passed through", req.idempotency_key === "key-abc");

  // Deliberately NOT normalized: repairing a non-canonical UUID would hide backend drift behind a
  // client fix. The server's truthful 422 is the correct outcome.
  const upper = { ...TUPLE, snapshot_id: SNAP.toUpperCase(), workflow_version_id: WF.toUpperCase() };
  const raw = signOffRequest(upper, "k");
  check("UUIDs are NOT lowercased / normalized by the client",
    raw.snapshot_id === SNAP.toUpperCase() && raw.workflow_version_id === WF.toUpperCase());

  check("path carries gate and slot and nothing else",
    signOffPath(GATE, SLOT) === `/gw/gates/${GATE}/slots/${SLOT}/sign-off`);
  check("path encodes hostile identifiers", signOffPath("a/b", "c d").includes("a%2Fb"));
}

console.log("\n#449 — attemptability gates presentation only, and fails closed (Q5/Q6)");
{
  const ok = attemptability(model(), GATE, SLOT);
  check("available + complete tuple + matching target is attemptable", ok.attemptable === true);
  check("attemptable exposes the server tuple unchanged",
    ok.attemptable && ok.tuple.snapshot_id === SNAP);

  check("available:false is never attemptable",
    attemptability(model({ available: false }), GATE, SLOT).reason === "server_not_available");
  check("withheld tuple is never attemptable",
    attemptability(model({ target_package_tuple: null }), GATE, SLOT).reason === "no_complete_tuple");

  // A partial tuple is never assembled — each member independently disqualifies.
  for (const key of ["gate_id", "slot_id", "snapshot_id", "workflow_version_id"] as const) {
    const partial = { ...TUPLE, [key]: "" } as ApprovalPreflightTuple;
    check(`blank ${key} refuses the action`,
      attemptability(model({ target_package_tuple: partial }), GATE, SLOT).attemptable === false);
  }
  for (const key of ["topic_revision", "script_revision"] as const) {
    const partial = { ...TUPLE, [key]: null } as unknown as ApprovalPreflightTuple;
    check(`missing ${key} refuses the action`,
      attemptability(model({ target_package_tuple: partial }), GATE, SLOT).reason === "no_complete_tuple");
  }

  // Q6 — refusal, not reconciliation.
  check("tuple gate != route gate fails closed",
    attemptability(model(), "99999999-9999-9999-9999-999999999999", SLOT).reason === "target_mismatch");
  check("tuple slot != route slot fails closed",
    attemptability(model(), GATE, "S2").reason === "target_mismatch");

  check("every attemptability reason has copy",
    (["attemptable", "server_not_available", "no_complete_tuple", "target_mismatch"] as const)
      .every((r) => typeof ATTEMPTABILITY_COPY[r] === "string" && ATTEMPTABILITY_COPY[r].length > 20));
}

console.log("\n#449 — the idempotency key is scoped to the exact tuple (Q3)");
{
  check("identical tuples share an identity", tupleIdentity(TUPLE) === tupleIdentity({ ...TUPLE }));
  for (const key of ["gate_id", "slot_id", "snapshot_id", "workflow_version_id"] as const) {
    check(`a changed ${key} changes the identity`,
      tupleIdentity(TUPLE) !== tupleIdentity({ ...TUPLE, [key]: "different" }));
  }
  for (const key of ["topic_revision", "script_revision"] as const) {
    check(`a changed ${key} changes the identity`,
      tupleIdentity(TUPLE) !== tupleIdentity({ ...TUPLE, [key]: 99 }));
  }
  check("identity is not sent and not a server field",
    !Object.keys(signOffRequest(TUPLE, "k")).includes("identity"));
}

console.log("\n#449 — three distinct result classes, positively discriminated (Q1/Q2)");
{
  // Transport: postJson's own catch, status 0. Whether the command ran is UNKNOWN.
  const t = classifyFailure(new WriteError(0, { detail: "network unreachable" }));
  check("status 0 is transport, never an outcome", t.kind === "transport");

  // Server-authored canonical outcomes.
  for (const code of SIGNOFF_OUTCOMES) {
    const r = classifyFailure(serverError(409, code));
    check(`${code} classifies as a server outcome`, r.kind === "outcome");
  }

  // Seam refusals — V2's own boundary, prose detail. NOT a sign-off decision.
  const seam501 = classifyFailure(seamError(501, "workbench (V2) writes only in an explicit local/dev/test runtime"));
  check("501 runtime posture is a seam refusal", seam501.kind === "seam_refusal");
  check("501 seam refusal is deterministic -> no retry", !isRetryable(seam501));
  const seam403 = classifyFailure(seamError(403, "not in the workbench write boundary"));
  check("403 boundary refusal is a seam refusal", seam403.kind === "seam_refusal");
  check("403 seam refusal offers no retry", !isRetryable(seam403));
  // A 401 from the seam is the workbench boundary declining to sign, which is NOT the server's
  // `signoff_unauthenticated` outcome — the command was never reached.
  const seam401 = classifyFailure(seamError(401, "not authenticated"));
  const seam401IsRefusal = seam401.kind === "seam_refusal" && !isRetryable(seam401);
  check("seam 401 is the boundary declining, never a server sign-off result", seam401IsRefusal);
  // Q3 is narrow ON PURPOSE: a seam 503 is still a seam refusal and is NEVER re-sent under the same
  // opaque value. Treating it as transport would widen the approved contract by client judgement.
  const seam503 = classifyFailure(seamError(503, "tanaghom api unreachable"));
  check("seam 503 stays a seam refusal", seam503.kind === "seam_refusal");
  check("seam 503 is NOT re-sent under the same opaque value", !isRetryable(seam503));

  // A server 403 and a seam 403 are DIFFERENT facts at the same status.
  const server403 = classifyFailure(serverError(403, "signoff_not_authorized"));
  check("server 403 and seam 403 never collapse",
    server403.kind === "outcome" && seam403.kind === "seam_refusal");

  // Q2 — drift fails closed, keeps the raw code, offers no retry, is never a canonical outcome.
  const drift = classifyFailure(serverError(409, "signoff_maybe_ok"));
  check("unknown upstream code is contract drift", drift.kind === "contract_drift");
  check("drift preserves the raw code (cannot be masked)",
    drift.kind === "contract_drift" && drift.rawCode === "signoff_maybe_ok");
  check("drift offers no retry", !isRetryable(drift));
  check("drift is never presented as a canonical outcome",
    drift.kind === "contract_drift" && !isCanonicalOutcome((drift as { rawCode: string }).rawCode));

  // FastAPI's own array-form validation error is drift, NOT a seam refusal — it must not be absorbed.
  const arrayForm = new WriteError(422, [{ loc: ["body"], msg: "bad" }] as unknown as { error?: string });
  const av = classifyFailure(arrayForm);
  check("array-form 422 falls closed to drift, not seam refusal", av.kind === "contract_drift");

  // Any unrecognized shape falls to drift, never to "V2 declined".
  const weird = classifyFailure(new WriteError(500, {} as { error?: string }));
  check("unrecognized failure shape falls closed to drift", weird.kind === "contract_drift");

}

console.log("\n#449 — a 200 is a receipt only with the COMPLETE canonical shape");
{
  // The canonical membership must mirror engine._signoff_receipt exactly, in the server's own order.
  // If the server's receipt changes, this fails loudly instead of the surface quietly rendering a
  // subset while claiming verbatim.
  const canonical = [
    "signoff_id", "operation", "status", "gate_id", "slot_id", "snapshot_id",
    "topic_revision", "script_revision", "workflow_version_id", "recorded_at",
  ];
  check("exactly 10 canonical receipt members", RECEIPT_MEMBERS.length === 10);
  check("receipt membership matches engine._signoff_receipt in order",
    JSON.stringify([...RECEIPT_MEMBERS]) === JSON.stringify(canonical));

  const RECEIPT: Record<string, unknown> = {
    signoff_id: "9a1c0f8e-0000-4000-8000-00000000abcd",
    operation: SIGNOFF_OPERATION,
    status: "recorded",
    gate_id: GATE,
    slot_id: SLOT,
    snapshot_id: SNAP,
    topic_revision: 2,
    script_revision: 3,
    workflow_version_id: WF,
    recorded_at: "2026-08-09T12:00:00+00:00",
  };
  const full = classifySuccess(RECEIPT);
  check("a COMPLETE canonical receipt classifies as a receipt", full.kind === "receipt");
  check("the receipt is carried through unedited",
    full.kind === "receipt" && full.receipt.operation === SIGNOFF_OPERATION
      && full.receipt.recorded_at === "2026-08-09T12:00:00+00:00");

  // Every member independently disqualifies — a partial body is NEVER a rendered success.
  for (const member of RECEIPT_MEMBERS) {
    const omitted = { ...RECEIPT };
    delete omitted[member];
    const r = classifySuccess(omitted);
    check(`a receipt missing ${member} is drift, never success`, r.kind === "contract_drift");
    check(`the drift detail names the missing ${member}`,
      r.kind === "contract_drift" && r.detail.includes(member));
  }

  // The historical regression this fixes: signoff_id alone used to render as a recorded sign-off.
  check("a signoff_id-only body is drift, never a rendered success",
    classifySuccess({ signoff_id: "abc" }).kind === "contract_drift");

  // Wrong types are drift too — a stringified revision is not the server's integer.
  check("a non-integer topic_revision is drift",
    classifySuccess({ ...RECEIPT, topic_revision: "2" }).kind === "contract_drift");
  check("a blank signoff_id is drift",
    classifySuccess({ ...RECEIPT, signoff_id: "   " }).kind === "contract_drift");

  // The canonical operation is reconciled, and the unexpected value stays visible.
  const wrongOp = classifySuccess({ ...RECEIPT, operation: "publish" });
  check("a non-canonical operation is drift", wrongOp.kind === "contract_drift");
  check("the unexpected operation is carried through, not swallowed",
    wrongOp.kind === "contract_drift" && wrongOp.rawCode === "publish");

  // The canonical status is PINNED to the contract literal: engine._signoff_receipt emits 'recorded'
  // on both the recording path and the idempotent replay, so any other value is drift rather than a
  // lifecycle word this surface invents a meaning for.
  check("SIGNOFF_RECEIPT_STATUS is the contract literal", SIGNOFF_RECEIPT_STATUS === "recorded");
  for (const bogus of ["pending", "void", "approved", "Recorded"]) {
    const wrongStatus = classifySuccess({ ...RECEIPT, status: bogus });
    check(`status "${bogus}" is drift, never a rendered success`,
      wrongStatus.kind === "contract_drift");
    check(`the unexpected status "${bogus}" is carried through, not swallowed`,
      wrongStatus.kind === "contract_drift" && wrongStatus.rawCode === bogus);
  }

  // KEY-SET EQUALITY: rendering is derived from RECEIPT_MEMBERS, so an unexpected member would be
  // silently DROPPED while the surface still claimed verbatim. Presence-only validation cannot see
  // that, so an unfamiliar member fails closed and is named.
  const extra = classifySuccess({ ...RECEIPT, actor: "someone", coverage: 3 });
  check("a receipt with unexpected members is drift", extra.kind === "contract_drift");
  check("the unexpected member names are reported, not dropped",
    extra.kind === "contract_drift" && extra.detail.includes("actor") && extra.detail.includes("coverage"));
  check("the unexpected-member drift explains the silent-drop risk",
    extra.kind === "contract_drift" && extra.detail.includes("silently drop"));
  // A leaked principal-bearing member must never render as part of a receipt.
  check("an unexpected principal member is drift, never rendered",
    classifySuccess({ ...RECEIPT, principal_id: "p-1" }).kind === "contract_drift");

  check("a null success body is drift", classifySuccess(null).kind === "contract_drift");
  check("an array success body is drift", classifySuccess([RECEIPT]).kind === "contract_drift");
  check("an empty success body is drift", classifySuccess({}).kind === "contract_drift");
}

console.log("\n#449 — no authority inference in any emitted copy (Q4 + directive line 47)");
{
  // The /gw route signs its OWN principal (a fixture principal when IAM is off), so second-person or
  // permission-granting copy would be false there and unprovable in general. #447/#448 disclose no
  // principal at all. Every string must describe THE REQUEST or THE TARGET, never the operator.
  const FORBIDDEN = [
    "you are", "you can", "you may", "you're", "your ", "you will", "you should",
    "permission", "permitted", "allowed to", "eligible to", "authorized to",
    "ready to sign", "may sign off", "can sign off", "will succeed", "guaranteed",
  ];
  const copy = [
    ...Object.values(OUTCOME_COPY),
    ...Object.values(ATTEMPTABILITY_COPY),
    nonOutcomeCopy({ kind: "seam_refusal", status: 501, detail: "" }),
    nonOutcomeCopy({ kind: "transport", detail: "" }),
    nonOutcomeCopy({ kind: "contract_drift", status: 500, rawCode: null, detail: "" }),
  ];
  for (const phrase of FORBIDDEN) {
    check(`no emitted copy contains "${phrase}"`,
      copy.every((s) => !s.toLowerCase().includes(phrase)));
  }
  check('no emitted copy uses a standalone "you"',
    copy.every((s) => !/\byou\b/i.test(s)));

  // Q4 — an already-recorded sign-off is never spun into "your earlier attempt worked".
  const already = OUTCOME_COPY.signoff_already_recorded.toLowerCase();
  check("signoff_already_recorded infers no prior success",
    !already.includes("succeed") && !already.includes("your earlier") && already.includes("makes no claim"));

  // Attemptable copy must not promise an outcome.
  const att = ATTEMPTABILITY_COPY.attemptable.toLowerCase();
  check("attemptable copy states attemptability, not permission",
    att.includes("attemptable") && att.includes("not a statement"));

  // Non-outcome classes must explicitly disclaim being a sign-off decision.
  check("seam-refusal copy denies being a sign-off decision",
    nonOutcomeCopy({ kind: "seam_refusal", status: 501, detail: "" })
      .toLowerCase().includes("not a sign-off decision"));
  check("transport copy states the outcome is unknown",
    nonOutcomeCopy({ kind: "transport", detail: "" }).toLowerCase().includes("unknown"));
  check("drift copy infers no outcome",
    nonOutcomeCopy({ kind: "contract_drift", status: 500, rawCode: null, detail: "" })
      .toLowerCase().includes("no outcome"));
}

console.log("\n#449 — retry policy is safe by construction");
{
  check("a canonical outcome is never retried",
    SIGNOFF_OUTCOMES.every((c) => !isRetryable({ kind: "outcome", code: c, status: 409 })));
  check("a receipt is never retried",
    !isRetryable({ kind: "receipt", receipt: { signoff_id: "x" } as never }));
  check("transport is the ONLY re-sendable class (original receipt, not a false conflict)",
    isRetryable({ kind: "transport", detail: "" }));
}

assert.equal(typeof failures, "number");
console.log(failures === 0 ? "\nALL PASS\n" : `\n${failures} FAILURE(S)\n`);
process.exit(failures === 0 ? 0 : 1);
