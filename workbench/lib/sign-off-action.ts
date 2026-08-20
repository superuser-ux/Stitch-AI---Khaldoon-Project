// #449 — pure, JSX-free logic for the V2 final-review sign-off action surface.
//
// V2 IS THE PRIMARY PRODUCT SURFACE, BUT IT IS NOT AN AUTHORITY. Every decision that matters is the
// merged server contract's (#439/#440): `SignOffBody` is `extra="forbid"`, the /gw route resolves and
// signs the principal SERVER-SIDE, and `engine.sign_off` owns the package comparison, the idempotency
// digest, the one-time-tuple rule, present-state revalidation, the receipt + its audit, and the typed
// refusal. This module forwards, classifies, and renders. It determines nothing.
//
// Invariants enforced HERE so no component branch can violate them by accident:
//
//   1. THE FOUR BINDING FIELDS ARE FORWARDED VERBATIM from the server-authored #448 preflight tuple.
//      Never derived, joined, recomputed, edited, substituted, or normalized — deliberately NOT even
//      lowercased, because repairing a non-canonical UUID would hide backend drift behind a client fix
//      (the server's truthful 422 is the correct outcome).
//   2. THREE DISTINCT RESULT CLASSES (Codex Q1). A server-authored canonical outcome, a SEAM REFUSAL
//      (V2's own /gw boundary declining before any upstream request), and a TRANSPORT failure are
//      different facts. Collapsing them lies in a specific direction: a seam refusal rendered as an
//      outcome asserts the sign-off authority denied the operator when the gate API was never asked.
//   3. AN UNRECOGNIZED UPSTREAM CODE IS CONTRACT DRIFT (Codex Q2), never a new result code. It fails
//      closed as a neutral, non-authority condition, offers no retry, and ALWAYS carries the raw code
//      so the drift cannot be masked. Nothing here is ever sent to the server.
//   4. NO AUTHORITY INFERENCE. Copy describes THE REQUEST, never the operator. The seam signs its own
//      principal, so "you are not authorized" is false in the IAM-off case and unprovable in general —
//      and #447/#448 disclose no principal at all (`authorization_evaluated` is always false).
//   5. NO OPTIMISTIC TRANSITION. Nothing here reports success that the server did not author, and a
//      transport-uncertain attempt is never inferred to have succeeded (Codex Q4).

// Type-only import on purpose: this module must carry NO runtime dependency on read-model, so it stays
// loadable under the `node --experimental-strip-types` unit seam (a value import would need a `.ts`
// specifier — the same extensionless-import trap that breaks lib/principal-proxy.ts under that loader).
import type {
  ApprovalPreflight,
  ApprovalPreflightTuple,
  SignOffReceipt,
  SignOffRequest,
  WriteError,
} from "./read-model";

/** #449 — the EXACT canonical final-review sign-off outcome vocabulary (#440).
 *
 *  This MIRRORS `engine.SIGNOFF_ERROR_STATUS`; it does not define it. Tanaghom is the sole authority
 *  for what a sign-off attempt can result in, and V2 renders these codes VERBATIM — it never invents,
 *  renames, translates, merges, or re-ranks one, and never sends one.
 *
 *  It is declared ONCE, here, for a specific reason: it is the only place a drift in the merged
 *  contract can be caught. The focused test asserts this exact 11-member set, so a change to the
 *  server vocabulary fails loudly instead of silently mis-rendering as an unrecognized code. */
export const SIGNOFF_OUTCOMES = [
  "signoff_unauthenticated",
  "signoff_not_authorized",
  "signoff_hard_floor",
  "signoff_target_unavailable",
  "signoff_package_mismatch",
  "signoff_blocked",
  "signoff_stale",
  "signoff_already_recorded",
  "idempotency_key_mismatch",
  "signoff_conflict",
  "invalid_request",
] as const;

export type SignOffOutcome = (typeof SIGNOFF_OUTCOMES)[number];

/** The canonical vocabulary as a lookup. Mirrors `engine.SIGNOFF_ERROR_STATUS`; defines nothing. */
const CANONICAL: ReadonlySet<string> = new Set<string>(SIGNOFF_OUTCOMES);

export function isCanonicalOutcome(code: unknown): code is SignOffOutcome {
  return typeof code === "string" && CANONICAL.has(code);
}

// --------------------------------------------------------------------------- //
// Attemptability — presentation gating ONLY (directive line 20; Codex Q5/Q6)
// --------------------------------------------------------------------------- //

/** Why the action is or is not offered. `attemptable` means the server-authored preflight says this
 *  target may be ATTEMPTED — never that it is authorized, permitted, ready, or will succeed. The
 *  command revalidates present state and authority and can still refuse. */
export type Attemptability =
  | { attemptable: true; reason: "attemptable"; tuple: ApprovalPreflightTuple }
  | { attemptable: false; reason: "server_not_available" | "no_complete_tuple" | "target_mismatch" };

/**
 * Decide whether the sign-off action may be OFFERED for this route target.
 *
 * Fail-closed, in the server's own order:
 *   • `available === false` — the server denied; no control is offered at all (not a disabled control
 *     with a local explanation: the reason is the server's, and the preflight surface already shows it);
 *   • no complete six-member tuple — there is nothing verbatim to forward, and a partial pin is never
 *     assembled (the server itself refuses to emit one);
 *   • tuple target != route target — REFUSE. This is a refusal, not a derivation: nothing is
 *     reconciled, chosen, or substituted. Sending one target's pins to another target's endpoint would
 *     produce a server-side `signoff_package_mismatch` indexed against the wrong target.
 */
export function attemptability(
  model: ApprovalPreflight,
  routeGateId: string,
  routeSlotId: string,
): Attemptability {
  if (!model.available) return { attemptable: false, reason: "server_not_available" };
  const tuple = model.target_package_tuple;
  if (!tuple) return { attemptable: false, reason: "no_complete_tuple" };
  for (const value of [tuple.snapshot_id, tuple.workflow_version_id, tuple.gate_id, tuple.slot_id]) {
    if (typeof value !== "string" || value.trim() === "") {
      return { attemptable: false, reason: "no_complete_tuple" };
    }
  }
  if (!Number.isInteger(tuple.topic_revision) || !Number.isInteger(tuple.script_revision)) {
    return { attemptable: false, reason: "no_complete_tuple" };
  }
  if (tuple.gate_id !== routeGateId || tuple.slot_id !== routeSlotId) {
    return { attemptable: false, reason: "target_mismatch" };
  }
  return { attemptable: true, reason: "attemptable", tuple };
}

/** Neutral copy for a non-attemptable target. States the SERVER's position, claims no authority, and
 *  never tells the operator what they may or may not do. */
export const ATTEMPTABILITY_COPY: Record<Attemptability["reason"], string> = {
  attemptable:
    "The server-authored preflight reports this package as presently attemptable. It is not a " +
    "statement that the sign-off will be accepted: the command revalidates present state and " +
    "authority when it runs.",
  server_not_available:
    "The server-authored preflight does not report this package as presently attemptable, so no " +
    "sign-off request is offered. The preflight surface shows the server's reason.",
  no_complete_tuple:
    "The server did not return a complete six-member package tuple, so there is nothing to forward " +
    "verbatim. A partial package is never assembled here.",
  target_mismatch:
    "The server-authored package tuple identifies a different gate/slot than this route, so no " +
    "request is sent. This surface reconciles nothing.",
};

// --------------------------------------------------------------------------- //
// The request (Codex Q3) — four verbatim fields + one opaque key, and nothing else
// --------------------------------------------------------------------------- //

/**
 * A STABLE identity for the exact six-member tuple, used only to scope the idempotency key locally.
 *
 * This is a local state key, not a derivation of server truth: it is never sent, never displayed, and
 * never interpreted. It exists so the key can be discarded the moment the pinned package changes —
 * reusing a key against a different tuple would produce a different server-side request digest and a
 * truthful `idempotency_key_mismatch`.
 */
export function tupleIdentity(tuple: ApprovalPreflightTuple): string {
  return JSON.stringify([
    tuple.gate_id, tuple.slot_id, tuple.snapshot_id,
    tuple.topic_revision, tuple.script_revision, tuple.workflow_version_id,
  ]);
}

/**
 * Build the exact request body.
 *
 * The four binding fields are copied straight off the server-authored tuple with NO transformation of
 * any kind. `gate_id`/`slot_id` are deliberately absent — they are route parameters only, and
 * `SignOffBody` would reject them as unknown fields.
 */
export function signOffRequest(tuple: ApprovalPreflightTuple, idempotencyKey: string): SignOffRequest {
  return {
    snapshot_id: tuple.snapshot_id,
    topic_revision: tuple.topic_revision,
    script_revision: tuple.script_revision,
    workflow_version_id: tuple.workflow_version_id,
    idempotency_key: idempotencyKey,
  };
}

/** The upstream path. `gate_id`/`slot_id` travel in the path and nowhere else. */
export function signOffPath(gateId: string, slotId: string): string {
  return `/gw/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/sign-off`;
}

// --------------------------------------------------------------------------- //
// Result classification (Codex Q1 + Q2)
// --------------------------------------------------------------------------- //

export type SignOffResult =
  /** The server recorded a receipt, or replayed the original one for an identical key. */
  | { kind: "receipt"; receipt: SignOffReceipt }
  /** A server-authored canonical refusal (#440). Rendered verbatim; never reinterpreted. */
  | { kind: "outcome"; code: SignOffOutcome; status: number }
  /** V2's OWN /gw boundary declined before any upstream request. Not a sign-off decision, and never
   *  a transport retry: the approved Q3 contract reuses the opaque key for an identical TRANSPORT
   *  retry only, so no seam refusal — including a 503 — re-sends this request. */
  | { kind: "seam_refusal"; status: number; detail: string }
  /** The request never produced a response. Whether it reached the server is UNKNOWN. */
  | { kind: "transport"; detail: string }
  /** Contract drift: an upstream result outside the canonical vocabulary. Fails closed, neutral. */
  | { kind: "contract_drift"; status: number; rawCode: string | null; detail: string };

/** The canonical `operation` the #439/#440 command reports on every receipt and idempotent replay.
 *  Mirrors `engine._signoff_receipt`; it is a contract literal, not a client-chosen label. */
export const SIGNOFF_OPERATION = "sign_off";

/** The canonical `status`. `engine._signoff_receipt` emits the literal `'recorded'` on BOTH the
 *  recording path and the idempotent replay — there is no other value in the contract, so accepting
 *  one would let a non-canonical lifecycle word render as a recorded sign-off. */
export const SIGNOFF_RECEIPT_STATUS = "recorded";

/** The complete canonical receipt membership, in the server's own order. Mirrors
 *  `engine._signoff_receipt` exactly — ten members, none optional. */
export const RECEIPT_MEMBERS = [
  "signoff_id",
  "operation",
  "status",
  "gate_id",
  "slot_id",
  "snapshot_id",
  "topic_revision",
  "script_revision",
  "workflow_version_id",
  "recorded_at",
] as const;

/** The two integer members; every other canonical member is non-blank text. */
const RECEIPT_INT_MEMBERS = ["topic_revision", "script_revision"] as const;
const RECEIPT_TEXT_MEMBERS = RECEIPT_MEMBERS.filter(
  (m): m is Exclude<(typeof RECEIPT_MEMBERS)[number], (typeof RECEIPT_INT_MEMBERS)[number]> =>
    !(RECEIPT_INT_MEMBERS as readonly string[]).includes(m),
);

/**
 * Classify a 200 response.
 *
 * A success body is accepted as a receipt ONLY when it carries the COMPLETE canonical shape — all ten
 * members of `engine._signoff_receipt`, each of the right type, and the canonical `operation`.
 * Anything short of that is contract drift.
 *
 * WHY THE FULL SHAPE, NOT A SPOT CHECK. A fabricated success is the single worst outcome this surface
 * could produce, and a partial body is exactly how one would arise: an `signoff_id`-only response
 * would previously have rendered as a recorded sign-off while every other field displayed as
 * `undefined`, presenting server truth the server never sent. Validating the whole membership makes
 * "renders the receipt verbatim" a checked property rather than a promise.
 *
 * The drift detail NAMES the offending members, so the drift is reported rather than masked (Q2). No
 * value is repaired, defaulted, or substituted — the response is either canonical or it is drift.
 */
export function classifySuccess(body: unknown): SignOffResult {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return {
      kind: "contract_drift",
      status: 200,
      rawCode: null,
      detail: "the server returned a success response that is not a sign-off receipt object",
    };
  }
  const r = body as Record<string, unknown>;
  const invalid: string[] = [];
  for (const member of RECEIPT_TEXT_MEMBERS) {
    const value = r[member];
    if (typeof value !== "string" || value.trim() === "") invalid.push(member);
  }
  for (const member of RECEIPT_INT_MEMBERS) {
    if (!Number.isInteger(r[member])) invalid.push(member);
  }
  if (invalid.length) {
    return {
      kind: "contract_drift",
      status: 200,
      rawCode: null,
      detail:
        "the server returned a success response that does not carry a complete sign-off receipt; " +
        `missing or invalid: ${invalid.join(", ")}`,
    };
  }
  // KEY-SET EQUALITY, not merely "the required members are present".
  //
  // Rendering is derived from RECEIPT_MEMBERS, so an unexpected member would be silently DROPPED —
  // the surface would display ten fields and call it verbatim while withholding something the server
  // actually sent. Presence-only validation cannot see that. An unfamiliar member is a signal the
  // receipt contract moved, so it fails closed as drift and the unexpected names are reported.
  const unexpected = Object.keys(r).filter(
    (k) => !(RECEIPT_MEMBERS as readonly string[]).includes(k),
  );
  if (unexpected.length) {
    return {
      kind: "contract_drift",
      status: 200,
      rawCode: null,
      detail:
        "the server returned a receipt carrying members outside the canonical shape, which this " +
        `surface would silently drop; unexpected: ${unexpected.join(", ")}`,
    };
  }
  // The canonical operation is reconciled, not assumed. A receipt reporting a different operation is
  // drift: this surface renders sign-off receipts and must not present some other command's result
  // as one. The unexpected value is carried through so it is visible rather than swallowed.
  if (r.operation !== SIGNOFF_OPERATION) {
    return {
      kind: "contract_drift",
      status: 200,
      rawCode: String(r.operation),
      detail:
        `the server returned a receipt whose operation is not the canonical ${SIGNOFF_OPERATION}`,
    };
  }
  // The canonical status is pinned for the same reason. `engine._signoff_receipt` emits `'recorded'`
  // on both the recording path and the idempotent replay, so any other value is drift — never a
  // lifecycle state this surface invents a meaning for.
  if (r.status !== SIGNOFF_RECEIPT_STATUS) {
    return {
      kind: "contract_drift",
      status: 200,
      rawCode: String(r.status),
      detail:
        `the server returned a receipt whose status is not the canonical ${SIGNOFF_RECEIPT_STATUS}`,
    };
  }
  return { kind: "receipt", receipt: r as unknown as SignOffReceipt };
}

/**
 * Classify a failed attempt into exactly one of the four failure classes.
 *
 * The discrimination is STRUCTURAL and positive, not a guess:
 *   • `status === 0`            — `postJson`'s own catch: no response at all -> TRANSPORT.
 *   • an `error` key survives   — the gate API raises `HTTPException(status, {"error": code})` for
 *     `postJson`'s unwrapping     every mapped sign-off failure, so an `error` key means the request
 *                                 REACHED the command. Canonical -> outcome; anything else -> DRIFT.
 *   • `detail` is a string      — every /gw refusal returns `{detail: "<prose>"}` -> SEAM REFUSAL.
 *   • anything else             — including FastAPI's own array-form validation 422 -> DRIFT.
 *
 * The fallthrough deliberately lands on DRIFT rather than on seam refusal, so an unrecognized shape
 * can never be quietly absorbed as "V2 declined" (Codex Q2: the drift must not be masked).
 */
export function classifyFailure(err: WriteError): SignOffResult {
  if (err.status === 0) {
    return { kind: "transport", detail: err.message || "the request did not reach the server" };
  }
  const raw = err.error;
  if (typeof raw === "string" && raw.trim() !== "") {
    if (isCanonicalOutcome(raw)) return { kind: "outcome", code: raw, status: err.status };
    return {
      kind: "contract_drift",
      status: err.status,
      rawCode: raw,
      detail: "the server returned a result code outside the canonical sign-off vocabulary",
    };
  }
  const body = err.detail as { detail?: unknown } | undefined;
  if (body && typeof body.detail === "string") {
    // NO seam refusal is retried with the opaque key, at ANY status. The approved Q3 contract permits
    // key reuse for an identical TRANSPORT retry only, and a seam refusal is a distinct class by
    // Q1 — treating a 503 as transport would silently widen that contract. A transient seam 503 is
    // therefore surfaced truthfully and left to a fresh, explicitly re-read attempt.
    return { kind: "seam_refusal", status: err.status, detail: body.detail };
  }
  return {
    kind: "contract_drift",
    status: err.status,
    rawCode: null,
    detail: "the server returned a failure in an unrecognized shape",
  };
}

/**
 * May this exact request be re-sent with the SAME opaque idempotency value?
 *
 * EXACTLY ONE class qualifies: a TRANSPORT failure. That is the approved Q3 contract, stated
 * narrowly and implemented narrowly. A transport failure is the only case where the request produced
 * no response at all, so whether the command ran is genuinely unknown — and reusing the value is what
 * makes the retry safe: an identical value + identical server-side digest returns the ORIGINAL
 * receipt instead of a fabricated `signoff_already_recorded`.
 *
 * A seam refusal (at ANY status, 503 included), a canonical outcome, contract drift, and a receipt
 * are never re-sent. Widening this to a seam 503 would treat a distinct Q1 class as transport and
 * silently broaden Q3; that needs an explicit contract amendment, not a client-side judgement call.
 */
export function isRetryable(result: SignOffResult): boolean {
  return result.kind === "transport";
}

// --------------------------------------------------------------------------- //
// Copy — about THE REQUEST, never about the operator (Codex Q1/Q4/Q5)
// --------------------------------------------------------------------------- //

/**
 * Neutral copy per canonical outcome.
 *
 * Every line is phrased as a property of the request or the target. None says "you", none names a
 * permission, none offers remediation that would imply what the operator could obtain, and none
 * asserts an identity: the /gw route signs its OWN principal (a fixture principal when IAM is off), so
 * a "you are not authorized" reading would be false there and unprovable in general.
 *
 * `signoff_already_recorded` deliberately does NOT say "your earlier attempt probably succeeded"
 * (Codex Q4) — the client never saw a receipt, and inferring one would be an authority claim.
 */
export const OUTCOME_COPY: Record<SignOffOutcome, string> = {
  signoff_unauthenticated:
    "The server rejected the request as unauthenticated. No signed principal reached the sign-off " +
    "command; nothing was recorded.",
  signoff_not_authorized:
    "The server refused this sign-off request: the signing principal is not authorized for this " +
    "target. Nothing was recorded.",
  signoff_hard_floor:
    "The server refused this sign-off request against the actor-model hard floor for this stage. " +
    "Nothing was recorded.",
  signoff_target_unavailable:
    "The server found no immutable target package for this gate and slot. Nothing was recorded.",
  signoff_package_mismatch:
    "The forwarded package tuple does not match the package the server has stored for this target. " +
    "Nothing was recorded; re-read the preflight for the current pinned package.",
  signoff_blocked:
    "The server refused this sign-off against present state (rejected, request-change, parked, or " +
    "unavailable/ambiguous). Nothing was recorded.",
  signoff_stale:
    "The server refused this sign-off as stale: the governed head or the package revisions have " +
    "moved. Nothing was recorded; re-read the preflight.",
  signoff_already_recorded:
    "The server reports a sign-off already recorded for this exact package tuple under a different " +
    "idempotency key. This request recorded nothing, and this surface makes no claim about who " +
    "recorded the existing one — re-read the preflight for the authoritative state.",
  idempotency_key_mismatch:
    "The server has already seen this idempotency key for a different request. Nothing was recorded.",
  signoff_conflict:
    "The server reported a conflict while recording (a concurrent attempt on the same target). " +
    "Nothing was recorded; re-read the preflight before attempting again.",
  invalid_request:
    "The server rejected the request as malformed. Nothing was recorded.",
};

/** Copy for the classes that are NOT server sign-off decisions. Each states plainly that the command
 *  was never reached or that its result is unknown — never that authority denied anything. */
export function nonOutcomeCopy(result: SignOffResult): string {
  switch (result.kind) {
    case "seam_refusal":
      return (
        "The workbench boundary declined to issue this request, so the sign-off command was never " +
        "reached. This is not a sign-off decision and says nothing about authority or eligibility."
      );
    case "transport":
      return (
        "The request did not complete. Whether it reached the server is unknown, so nothing is " +
        "claimed about it here. Retrying reuses the same idempotency key, so if the command did run " +
        "the server returns the original receipt rather than recording a second one."
      );
    case "contract_drift":
      return (
        "The server returned a result this surface does not recognize. It is reported unchanged and " +
        "treated as unresolved; no outcome, authority, or eligibility is inferred from it."
      );
    default:
      return "";
  }
}
