import { createHmac } from "crypto";
import { resolveReviewerSecret, reviewerSecretStatus } from "./reviewer-secret-file";

export const REVIEWER_COOKIE = "tanaghom_reviewer";

// #147 (#146 S1) / #387 — the reviewer proxy secret never falls back to a public constant in a
// production/demo runtime. Resolution (direct env + the manager-neutral FILE seam, fail-closed) lives
// in ./reviewer-secret-file (a behavioural mirror of gates/reviewer_secret.py); the dev fallback is used
// ONLY under an explicit TANAGHOM_DEV_MODE opt-in and ONLY when neither source is configured. Accidental
// env omission or an invalid FILE fails closed (throws) instead of silently signing with a public key.

// resolved-source validity (env OR a valid FILE); the dev fixture / an invalid FILE are NOT reported
// configured. Boolean only — never the value or its content.
export function reviewerSecretConfigured(): boolean {
  return reviewerSecretStatus()[0];
}

function _secret(): string {
  return resolveReviewerSecret()[0];
}

export function signPrincipal(principalId: string) {
  return createHmac("sha256", _secret()).update(principalId, "utf8").digest("hex");
}

export function principalProxyHeaders(principalId: string) {
  return {
    "x-principal-id": principalId,
    "x-principal-signature": signPrincipal(principalId),
  };
}

