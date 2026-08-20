import { createHash, createHmac, randomBytes, timingSafeEqual } from "crypto";
import { providerRequestUrl } from "./oidc-provider-url";
import { principalProxyHeaders } from "./principal-proxy";
import { verifyIdToken } from "./oidc-token";
import { resolveSecret } from "./secure-secret-source";

export const IAM_SESSION_COOKIE = "tanaghom_iam_session";
export const OIDC_FLOW_COOKIE = "tanaghom_oidc_flow";
const SESSION_TTL_SECONDS = 8 * 60 * 60;
const FLOW_TTL_SECONDS = 10 * 60;
const DEV_SESSION_SECRET = "dev-internal-iam-session-secret";
const API_BASE = process.env.API_BASE || "http://localhost:8009";

type Discovery = {
  authorization_endpoint: string;
  token_endpoint: string;
  issuer: string;
  jwks_uri: string;
  end_session_endpoint?: string;
};

export type IamSession = {
  iss: string;
  sub: string;
  principal_id: string | null;
  display: string | null;
  email: string | null;
  exp: number;
};

export type OidcFlow = { state: string; nonce: string; verifier: string; exp: number };
export type BindingCheck = "ok" | "unbound" | "mismatch" | "unavailable";

const discoveryCache = new Map<string, Discovery>();

export function clearOidcDiscoveryCacheForTests(): void {
  discoveryCache.clear();
}

function assertProviderUrl(value: string, label: string): void {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${label} is not an absolute URL`);
  }
  if (!devMode() && url.protocol !== "https:") throw new Error(`${label} must use HTTPS`);
  if (url.username || url.password || url.hash) throw new Error(`${label} contains forbidden URL components`);
}

function enabled(value: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((value || "").trim().toLowerCase());
}

function devMode(): boolean {
  return enabled(process.env.TANAGHOM_DEV_MODE);
}

function sessionSecret(): string {
  return resolveSecret({
    envName: "TANAGHOM_SESSION_SECRET",
    fileEnvName: "TANAGHOM_SESSION_SECRET_FILE",
    maxAgeEnvName: "TANAGHOM_SESSION_SECRET_FILE_MAX_AGE_SECONDS",
    required: true,
    devFallback: DEV_SESSION_SECRET,
  }) as string;
}

export function iamEnabled(): boolean {
  return enabled(process.env.TANAGHOM_OIDC_ENABLED);
}

export function oidcConfig() {
  return {
    issuer: (process.env.TANAGHOM_OIDC_ISSUER || "").trim().replace(/\/$/, ""),
    internalBaseUrl: (process.env.TANAGHOM_OIDC_INTERNAL_BASE_URL || "").trim().replace(/\/$/, "") || null,
    clientId: (process.env.TANAGHOM_OIDC_CLIENT_ID || "").trim(),
    clientSecret: resolveSecret({
      envName: "TANAGHOM_OIDC_CLIENT_SECRET",
      fileEnvName: "TANAGHOM_OIDC_CLIENT_SECRET_FILE",
      maxAgeEnvName: "TANAGHOM_OIDC_CLIENT_SECRET_FILE_MAX_AGE_SECONDS",
      required: false,
    }),
    redirectUri: (process.env.TANAGHOM_OIDC_REDIRECT_URI || "").trim() || null,
    postLogoutRedirectUri: (process.env.TANAGHOM_OIDC_POST_LOGOUT_REDIRECT_URI || "").trim() || null,
  };
}

export async function discover(issuer: string, internalBaseUrl: string | null = null): Promise<Discovery> {
  assertProviderUrl(issuer, "OIDC issuer");
  if (internalBaseUrl) assertProviderUrl(internalBaseUrl, "OIDC internal base URL");
  const cacheKey = `${issuer}\n${internalBaseUrl || ""}`;
  const cached = discoveryCache.get(cacheKey);
  if (cached) return cached;
  const discoveryUrl = providerRequestUrl(
    `${issuer}/.well-known/openid-configuration`,
    issuer,
    internalBaseUrl,
  );
  const response = await fetch(discoveryUrl, { cache: "no-store" });
  if (!response.ok) throw new Error(`OIDC discovery failed: HTTP ${response.status}`);
  const document = await response.json() as Discovery;
  if (document.issuer !== issuer) throw new Error("OIDC discovery issuer mismatch");
  if (!document.authorization_endpoint || !document.token_endpoint || !document.jwks_uri) {
    throw new Error("OIDC discovery document is missing required endpoints");
  }
  assertProviderUrl(document.authorization_endpoint, "OIDC authorization endpoint");
  assertProviderUrl(document.token_endpoint, "OIDC token endpoint");
  assertProviderUrl(document.jwks_uri, "OIDC JWKS endpoint");
  if (document.end_session_endpoint) assertProviderUrl(document.end_session_endpoint, "OIDC logout endpoint");
  discoveryCache.set(cacheKey, document);
  return document;
}

const b64url = (value: Buffer) => value.toString("base64url");
export const randomToken = () => b64url(randomBytes(32));
export const pkceChallenge = (verifier: string) => b64url(createHash("sha256").update(verifier).digest());

function sign(payload: string): string {
  return createHmac("sha256", sessionSecret()).update(payload, "utf8").digest("hex");
}

function encodeSigned(value: object): string {
  const payload = b64url(Buffer.from(JSON.stringify(value), "utf8"));
  return `${payload}.${sign(payload)}`;
}

function decodeSigned<T>(raw: string | undefined): T | null {
  if (!raw) return null;
  const dot = raw.lastIndexOf(".");
  if (dot <= 0) return null;
  const payload = raw.slice(0, dot);
  const signature = raw.slice(dot + 1);
  const expected = sign(payload);
  if (signature.length !== expected.length
      || !timingSafeEqual(Buffer.from(signature, "utf8"), Buffer.from(expected, "utf8"))) {
    return null;
  }
  try {
    return JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as T;
  } catch {
    return null;
  }
}

export function sessionValue(session: Omit<IamSession, "exp">): string {
  return encodeSigned({ ...session, exp: Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS });
}

export function flowValue(flow: Omit<OidcFlow, "exp">): string {
  return encodeSigned({ ...flow, exp: Math.floor(Date.now() / 1000) + FLOW_TTL_SECONDS });
}

export function readSession(raw: string | undefined): IamSession | null {
  const session = decodeSigned<IamSession>(raw);
  if (!session || typeof session.exp !== "number" || session.exp <= Math.floor(Date.now() / 1000)) return null;
  if (typeof session.iss !== "string" || typeof session.sub !== "string") return null;
  return session;
}

export function readFlow(raw: string | undefined): OidcFlow | null {
  const flow = decodeSigned<OidcFlow>(raw);
  if (!flow || typeof flow.exp !== "number" || flow.exp <= Math.floor(Date.now() / 1000)) return null;
  return flow;
}

export async function exchangeCode(code: string, verifier: string, nonce: string, redirectUri: string) {
  const config = oidcConfig();
  const document = await discover(config.issuer, config.internalBaseUrl);
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    client_id: config.clientId,
    code_verifier: verifier,
  });
  if (config.clientSecret) body.set("client_secret", config.clientSecret);
  const response = await fetch(providerRequestUrl(
    document.token_endpoint,
    config.issuer,
    config.internalBaseUrl,
  ), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });
  if (!response.ok) throw new Error("token exchange failed");
  const tokens = await response.json() as { id_token?: string };
  if (!tokens.id_token) throw new Error("token response has no id_token");
  const payload = await verifyIdToken(tokens.id_token, {
    issuer: config.issuer,
    clientId: config.clientId,
    nonce,
    jwksUri: providerRequestUrl(document.jwks_uri, config.issuer, config.internalBaseUrl),
  });
  return { idToken: tokens.id_token, payload };
}

export async function resolveBinding(issuer: string, subject: string) {
  const response = await fetch(
    `${API_BASE}/identity/binding?issuer=${encodeURIComponent(issuer)}&subject=${encodeURIComponent(subject)}`,
    { headers: principalProxyHeaders("system"), cache: "no-store" },
  );
  if (!response.ok) throw new Error("identity binding lookup failed");
  return response.json() as Promise<{ principal_id: string | null; display_name_en?: string | null }>;
}

export async function revalidateBinding(session: IamSession): Promise<BindingCheck> {
  try {
    const binding = await resolveBinding(session.iss, session.sub);
    if (!binding.principal_id) return "unbound";
    return binding.principal_id === session.principal_id ? "ok" : "mismatch";
  } catch {
    return "unavailable";
  }
}
