import { createHmac } from "crypto";

// #292 — V2's SERVER-SIDE principal signing for the minimum enumerated write path.
//
// This is a deliberate, governed widening of #293's Stage 0 GET-only boundary, authorised by
// Codex's secondary ruling 2: "the minimum enumerated, server-side principal-signed write path
// required by #292. Reuse existing identity/authority enforcement; no client-held secret,
// client-asserted actor, IAM expansion, or general write proxy."
//
// It is a MIRROR of the transport contract, not a second authority:
//   - the same HMAC contract the gate API verifies (`gates/api.py:_trusted_principal`) and that
//     `dashboard/lib/reviewer-session.ts` already mirrors — the repo documents both sides reading
//     the same two env vars on purpose;
//   - signing happens ONLY here, server-side. The secret never reaches the browser;
//   - the actor is NEVER taken from the client body. It is the server-resolved principal, and the
//     gate API still authorises at decide time (#10) via _require_schedule_authority.
//
// Fail-closed exactly like V1: the dev fallback is used only under an explicit TANAGHOM_DEV_MODE
// opt-in; an accidental env omission (or an invalid FILE) throws rather than silently signing with a
// known-public key. #387 — resolution (direct env + the manager-neutral FILE seam) lives in
// ./reviewer-secret-file, a behavioural mirror of gates/reviewer_secret.py and dashboard's copy.
import { resolveReviewerSecret, reviewerSecretStatus, devMode as resolverDevMode } from "./reviewer-secret-file";

/** The EXPLICIT local/dev/test posture — an operator opts in with TANAGHOM_DEV_MODE, exactly as V1
 *  does. Nothing infers it, and it is never implied by the absence of IAM. Exported because the
 *  write route must refuse to sign at all outside this posture (see app/gw/[...path]/route.ts). */
export function devMode(): boolean {
  return resolverDevMode();
}

/** Resolved-source validity (env OR a valid FILE) — boolean only, never the value or its content. The
 *  same semantics the Python /health signal reports; the write route's posture gate (devMode + IAM-off)
 *  is unchanged and orthogonal to this. */
export function reviewerSecretConfigured(): boolean {
  return reviewerSecretStatus()[0];
}

function secret(): string {
  return resolveReviewerSecret()[0];
}

export function principalProxyHeaders(principalId: string) {
  return {
    "x-principal-id": principalId,
    "x-principal-signature": createHmac("sha256", secret()).update(principalId, "utf8").digest("hex"),
  };
}

/** Canonical identities available to the explicit local/acceptance fixture seam. This is deliberately
 * bounded to principals already defined by governed dev/acceptance fixtures. */
export const WORKBENCH_DEV_PRINCIPALS = ["khal", "huda"] as const;
type WorkbenchDevPrincipal = (typeof WORKBENCH_DEV_PRINCIPALS)[number];
const WORKBENCH_DEV_PRINCIPAL_ENV = "TANAGHOM_WORKBENCH_DEV_PRINCIPAL";

/** The operating principal V2 signs for. This is a FIXTURE identity, not a proof of who called: it
 *  cannot distinguish two callers, so the write route must never sign it in a runtime where an
 *  untrusted caller could reach it. The route therefore refuses to write unless the runtime is BOTH
 *  IAM-disabled AND in the explicit local/dev/test posture (devMode) — outside that, V2 fails closed
 *  rather than handing out this principal's signed authority. Proving a real caller identity is IAM
 *  integration, which is deliberately out of scope for this PR.
 *  Deliberately NOT read from the request body — a client may never assert who it is. */
export const WORKBENCH_PRINCIPAL = "khal";

/** Resolve the server-selected fixture principal for IAM-disabled development/acceptance runtimes.
 * The environment is runtime wiring, never product authority, and is rejected outside explicit
 * development/test mode. IAM-enabled callers use their authenticated session principal instead. */
export function workbenchPrincipal(): WorkbenchDevPrincipal {
  const configured = process.env[WORKBENCH_DEV_PRINCIPAL_ENV];
  if (configured == null || configured === "") return WORKBENCH_PRINCIPAL;
  if (!devMode()) {
    throw new Error(`${WORKBENCH_DEV_PRINCIPAL_ENV} is permitted only in an explicit local/dev/test runtime`);
  }
  if (!WORKBENCH_DEV_PRINCIPALS.includes(configured as WorkbenchDevPrincipal)) {
    throw new Error(`${WORKBENCH_DEV_PRINCIPAL_ENV} must be one of: ${WORKBENCH_DEV_PRINCIPALS.join(", ")}`);
  }
  return configured as WorkbenchDevPrincipal;
}
