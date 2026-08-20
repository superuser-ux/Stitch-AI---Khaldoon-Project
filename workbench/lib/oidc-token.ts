import { createPublicKey, verify as verifySignature, type JsonWebKey } from "crypto";

type Jwk = Record<string, unknown> & {
  alg?: string;
  key_ops?: string[];
  kid?: string;
  kty?: string;
  use?: string;
};

type CachedJwks = { expiresAt: number; keys: Jwk[] };
const jwksCache = new Map<string, CachedJwks>();
const DEFAULT_JWKS_TTL_MS = 5 * 60 * 1000;
const MAX_TOKEN_BYTES = 16 * 1024;

function decodeJsonPart(part: string): Record<string, unknown> | null {
  try {
    const decoded = Buffer.from(part, "base64url").toString("utf8");
    const value = JSON.parse(decoded) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function cacheTtlMs(header: string | null): number {
  const match = header?.match(/(?:^|,)\s*max-age=(\d+)/i);
  if (!match) return DEFAULT_JWKS_TTL_MS;
  const seconds = Number(match[1]);
  if (!Number.isFinite(seconds)) return DEFAULT_JWKS_TTL_MS;
  return Math.min(Math.max(seconds, 30), 60 * 60) * 1000;
}

async function fetchJwks(uri: string, force = false): Promise<Jwk[]> {
  const cached = jwksCache.get(uri);
  if (!force && cached && cached.expiresAt > Date.now()) return cached.keys;

  const response = await fetch(uri, { cache: "no-store" });
  if (!response.ok) throw new Error(`JWKS request failed: HTTP ${response.status}`);
  const document = await response.json() as { keys?: unknown };
  if (!Array.isArray(document.keys)) throw new Error("JWKS document has no keys array");
  const keys = document.keys.filter((value): value is Jwk => (
    Boolean(value) && typeof value === "object" && !Array.isArray(value)
  ));
  if (keys.length === 0) throw new Error("JWKS document has no usable keys");
  jwksCache.set(uri, {
    expiresAt: Date.now() + cacheTtlMs(response.headers.get("cache-control")),
    keys,
  });
  return keys;
}

function verificationKey(keys: Jwk[], kid: string): Jwk | null {
  const candidates = keys.filter((key) => key.kid === kid
    && key.kty === "RSA"
    && (!key.alg || key.alg === "RS256")
    && (!key.use || key.use === "sig")
    && (!key.key_ops || key.key_ops.includes("verify")));
  return candidates.length === 1 ? candidates[0] : null;
}

function signatureValid(jwt: string, key: Jwk): boolean {
  const parts = jwt.split(".");
  try {
    return verifySignature(
      "RSA-SHA256",
      Buffer.from(`${parts[0]}.${parts[1]}`, "ascii"),
      createPublicKey({ key: key as JsonWebKey, format: "jwk" }),
      Buffer.from(parts[2], "base64url"),
    );
  } catch {
    return false;
  }
}

export function decodeJwtPayload(jwt: string): Record<string, unknown> | null {
  const parts = jwt.split(".");
  return parts.length === 3 ? decodeJsonPart(parts[1]) : null;
}

export function validateIdTokenPayload(payload: Record<string, unknown>, opts: {
  issuer: string;
  clientId: string;
  nonce: string;
  now?: number;
}): string | null {
  const now = opts.now ?? Math.floor(Date.now() / 1000);
  if (typeof payload.iss !== "string" || payload.iss !== opts.issuer) return "issuer mismatch";
  const audiences = Array.isArray(payload.aud)
    ? payload.aud.filter((value): value is string => typeof value === "string")
    : typeof payload.aud === "string" ? [payload.aud] : [];
  if (!audiences.includes(opts.clientId)) return "audience mismatch";
  const azp = typeof payload.azp === "string" ? payload.azp : "";
  if (audiences.length > 1 && !azp) return "multi-audience token without authorized party (azp)";
  if (azp && azp !== opts.clientId) return "authorized party (azp) mismatch";
  if (typeof payload.exp !== "number" || payload.exp <= now) return "token expired";
  if (payload.nbf != null && (typeof payload.nbf !== "number" || payload.nbf > now + 60)) {
    return "token not active";
  }
  if (payload.iat != null && (typeof payload.iat !== "number" || payload.iat > now + 60)) {
    return "token issued in the future";
  }
  if (typeof payload.nonce !== "string" || payload.nonce !== opts.nonce) return "nonce mismatch";
  if (typeof payload.sub !== "string" || payload.sub.length === 0) return "missing subject";
  return null;
}

export async function verifyIdToken(jwt: string, opts: {
  issuer: string;
  clientId: string;
  nonce: string;
  jwksUri: string;
}): Promise<Record<string, unknown>> {
  if (!jwt || Buffer.byteLength(jwt, "utf8") > MAX_TOKEN_BYTES) {
    throw new Error("id_token is empty or too large");
  }
  const parts = jwt.split(".");
  if (parts.length !== 3 || parts.some((part) => !/^[A-Za-z0-9_-]+$/.test(part))) {
    throw new Error("id_token is not a compact JWT");
  }
  const header = decodeJsonPart(parts[0]);
  if (!header || header.alg !== "RS256") throw new Error("id_token algorithm is not allowed");
  if (typeof header.kid !== "string" || header.kid.length === 0) {
    throw new Error("id_token has no signing key id");
  }

  let keys = await fetchJwks(opts.jwksUri);
  let key = verificationKey(keys, header.kid);
  let valid = key ? signatureValid(jwt, key) : false;
  if (!valid) {
    // A key rotation can occur before the cache expires. Refresh once on kid miss or bad signature,
    // then fail closed if the provider still cannot prove the token.
    keys = await fetchJwks(opts.jwksUri, true);
    key = verificationKey(keys, header.kid);
    valid = key ? signatureValid(jwt, key) : false;
  }
  if (!valid) throw new Error("id_token signature is invalid");

  const payload = decodeJsonPart(parts[1]);
  if (!payload) throw new Error("id_token payload is unreadable");
  const invalid = validateIdTokenPayload(payload, opts);
  if (invalid) throw new Error(invalid);
  return payload;
}

export function clearOidcKeyCacheForTests(): void {
  jwksCache.clear();
}
