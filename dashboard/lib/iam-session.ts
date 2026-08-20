import { createHmac, createHash, randomBytes, timingSafeEqual } from "crypto";
export { decodeJwtPayload, validateIdTokenPayload, verifyIdToken } from "./oidc-token";

// #190 (#172 S1) — flagged OIDC login at the dashboard BFF. Server-side only.
//
// IAM proves identity; Tanaghom decides authority. This module handles ONLY authentication:
// standard OIDC authorization-code + PKCE against a provider-pluggable issuer (discovery-based;
// Keycloak-class is the dev target shape — no vendor commitment). The authenticated (issuer,
// subject) is resolved ONCE at the callback to its bound operating principal via the gate API's
// system-gated /identity/binding read; the session cookie then carries that principal and the
// /gw proxy signs it through the EXISTING x-principal-* contract. IdP claims (email/name) are
// display/provisioning hints only — they never feed authorization.
//
// ID-token acceptance is cryptographic: RS256 signature verification uses the issuer's discovered
// JWKS and refreshes once on key miss/signature failure so provider key rotation does not require a
// process restart. Issuer/audience/azp/expiry/nonce/subject claims are then validated exactly.

export const IAM_SESSION_COOKIE = "tanaghom_iam_session";
export const OIDC_FLOW_COOKIE = "tanaghom_oidc_flow";
const SESSION_TTL_SECONDS = 8 * 60 * 60;   // resolve-at-login; re-login picks up binding changes
const FLOW_TTL_SECONDS = 10 * 60;

// #147 pattern: never a silent public-constant fallback outside explicit dev mode.
const DEV_SESSION_SECRET = "dev-internal-iam-session-secret"; // local/dev/test ONLY

function _devMode(): boolean {
  return ["1", "true", "yes", "on"].includes((process.env.TANAGHOM_DEV_MODE || "").trim().toLowerCase());
}

function _sessionSecret(): string {
  const s = (process.env.TANAGHOM_SESSION_SECRET || "").trim();
  if (s) return s;
  if (_devMode()) return DEV_SESSION_SECRET;
  throw new Error("TANAGHOM_SESSION_SECRET is not configured. Set it for demo/production, "
    + "or set TANAGHOM_DEV_MODE=1 for local/dev/test.");
}

export function iamEnabled(): boolean {
  // The FLAG alone decides IAM mode. A half-configured deployment (flag on, issuer missing) must
  // fail loudly at login time — never silently degrade to demo identity (the #190 invariant).
  return ["1", "true", "yes", "on"].includes((process.env.TANAGHOM_OIDC_ENABLED || "").trim().toLowerCase());
}

export function oidcConfig() {
  return {
    issuer: (process.env.TANAGHOM_OIDC_ISSUER || "").trim().replace(/\/$/, ""),
    clientId: (process.env.TANAGHOM_OIDC_CLIENT_ID || "tanaghom-dashboard").trim(),
    clientSecret: (process.env.TANAGHOM_OIDC_CLIENT_SECRET || "").trim() || null,
    redirectUri: (process.env.TANAGHOM_OIDC_REDIRECT_URI || "").trim() || null, // else derived per request
  };
}

// --- issuer discovery (cached per issuer) -----------------------------------------------------
export type Discovery = {
  authorization_endpoint: string;
  token_endpoint: string;
  issuer: string;
  jwks_uri: string;
  end_session_endpoint?: string;
};
const discoveryCache = new Map<string, Discovery>();

function assertProviderUrl(value: string, label: string): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${label} is not an absolute URL`);
  }
  if (!_devMode() && url.protocol !== "https:") throw new Error(`${label} must use HTTPS`);
  if (url.username || url.password || url.hash) throw new Error(`${label} contains forbidden URL components`);
}

export async function discover(issuer: string): Promise<Discovery> {
  assertProviderUrl(issuer, "OIDC issuer");
  const cached = discoveryCache.get(issuer);
  if (cached) return cached;
  const res = await fetch(`${issuer}/.well-known/openid-configuration`, { cache: "no-store" });
  if (!res.ok) throw new Error(`OIDC discovery failed for ${issuer}: HTTP ${res.status}`);
  const doc = (await res.json()) as Discovery;
  if (doc.issuer !== issuer) throw new Error(`OIDC discovery issuer mismatch for ${issuer}`);
  if (!doc.authorization_endpoint || !doc.token_endpoint || !doc.jwks_uri) {
    throw new Error(`OIDC discovery document for ${issuer} is missing required endpoints`);
  }
  assertProviderUrl(doc.authorization_endpoint, "OIDC authorization endpoint");
  assertProviderUrl(doc.token_endpoint, "OIDC token endpoint");
  assertProviderUrl(doc.jwks_uri, "OIDC JWKS endpoint");
  if (doc.end_session_endpoint) assertProviderUrl(doc.end_session_endpoint, "OIDC logout endpoint");
  discoveryCache.set(issuer, doc);
  return doc;
}

// --- PKCE / random ----------------------------------------------------------------------------
const b64url = (b: Buffer) => b.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export const randomToken = () => b64url(randomBytes(32));
export const pkceChallenge = (verifier: string) => b64url(createHash("sha256").update(verifier).digest());

// --- signed cookie payloads (HMAC; httpOnly cookies set by the routes) -------------------------
function _sign(payload: string): string {
  return createHmac("sha256", _sessionSecret()).update(payload, "utf8").digest("hex");
}

export function encodeSigned(value: object): string {
  const payload = b64url(Buffer.from(JSON.stringify(value), "utf8"));
  return `${payload}.${_sign(payload)}`;
}

export function decodeSigned<T>(raw: string | undefined): T | null {
  if (!raw) return null;
  const dot = raw.lastIndexOf(".");
  if (dot <= 0) return null;
  const payload = raw.slice(0, dot);
  const sig = raw.slice(dot + 1);
  const expect = _sign(payload);
  if (sig.length !== expect.length
    || !timingSafeEqual(Buffer.from(sig, "utf8"), Buffer.from(expect, "utf8"))) return null;
  try {
    return JSON.parse(Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8")) as T;
  } catch {
    return null;
  }
}

export type IamSession = {
  iss: string; sub: string;
  principal_id: string | null;         // null = authenticated but UNBOUND (truthful, no fallback)
  display: string | null; email: string | null;
  exp: number;                          // unix seconds
};
export type OidcFlow = { state: string; nonce: string; verifier: string; exp: number };

export function sessionValue(session: Omit<IamSession, "exp">): string {
  return encodeSigned({ ...session, exp: Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS });
}

export function flowValue(flow: Omit<OidcFlow, "exp">): string {
  return encodeSigned({ ...flow, exp: Math.floor(Date.now() / 1000) + FLOW_TTL_SECONDS });
}

export function readSession(raw: string | undefined): IamSession | null {
  const s = decodeSigned<IamSession>(raw);
  if (!s || typeof s.exp !== "number" || s.exp <= Math.floor(Date.now() / 1000)) return null;
  return s;
}

export function readFlow(raw: string | undefined): OidcFlow | null {
  const f = decodeSigned<OidcFlow>(raw);
  if (!f || typeof f.exp !== "number" || f.exp <= Math.floor(Date.now() / 1000)) return null;
  return f;
}

// --- #194 per-request binding revalidation ------------------------------------------------------
// Immediate revocation: every authority-bearing BFF request re-proves that the session's
// integrity-protected (issuer, subject) STILL resolves to the same active principal the session
// carries, via the existing system-signed gate-API read. No S3 mechanics — same trust primitives.
import { principalProxyHeaders } from "./reviewer-session";
const GATE_API = process.env.API_BASE || "http://localhost:8009";

export type BindingCheck = "ok" | "unbound" | "mismatch" | "unavailable";

export async function revalidateBinding(session: IamSession): Promise<BindingCheck> {
  try {
    const res = await fetch(
      `${GATE_API}/identity/binding?issuer=${encodeURIComponent(session.iss)}&subject=${encodeURIComponent(session.sub)}`,
      { headers: principalProxyHeaders("system"), cache: "no-store" },
    );
    if (!res.ok) return "unavailable";
    const data = (await res.json()) as { principal_id: string | null };
    if (!data.principal_id) return "unbound";           // binding absent or deactivated
    return data.principal_id === session.principal_id ? "ok" : "mismatch";
  } catch {
    return "unavailable";                                // transient — fail closed WITHOUT logout
  }
}
