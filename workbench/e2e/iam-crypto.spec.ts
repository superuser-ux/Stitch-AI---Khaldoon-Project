import { expect, test } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { generateKeyPairSync, sign } from "node:crypto";
import { clearOidcKeyCacheForTests, verifyIdToken } from "../lib/oidc-token";
import { providerRequestUrl } from "../lib/oidc-provider-url";
import { clearOidcDiscoveryCacheForTests, discover } from "../lib/iam-session";
import { resolveAllowedPath, resolveAllowedQuery, resolveAllowedWritePath } from "../lib/api-contract";

const PORT = 3118;
const ISSUER = `http://127.0.0.1:${PORT}`;
const CLIENT_ID = "tanaghom-workbench";
const NONCE = "nonce-1";
const pair1 = generateKeyPairSync("rsa", { modulusLength: 2048 });
const pair2 = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk1 = { ...pair1.publicKey.export({ format: "jwk" }), kid: "key-1", alg: "RS256", use: "sig" };
const jwk2 = { ...pair2.publicKey.export({ format: "jwk" }), kid: "key-2", alg: "RS256", use: "sig" };
let keys = [jwk1];
let server: Server;

function token(kid: string, privateKey: typeof pair1.privateKey, claims: Record<string, unknown> = {}) {
  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT", kid })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    iss: ISSUER,
    sub: "subject-1",
    aud: CLIENT_ID,
    nonce: NONCE,
    iat: now,
    exp: now + 300,
    ...claims,
  })).toString("base64url");
  const signature = sign("RSA-SHA256", Buffer.from(`${header}.${payload}`), privateKey).toString("base64url");
  return `${header}.${payload}.${signature}`;
}

const options = { issuer: ISSUER, clientId: CLIENT_ID, nonce: NONCE, jwksUri: `${ISSUER}/jwks` };

test.describe("cryptographic OIDC ID-token verification", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async () => {
    server = createServer((request, response) => {
      if (request.url === "/jwks") {
        response.setHeader("content-type", "application/json");
        response.setHeader("cache-control", "public, max-age=3600");
        response.end(JSON.stringify({ keys }));
        return;
      }
      response.statusCode = 404;
      response.end();
    });
    await new Promise<void>((resolve) => server.listen(PORT, "127.0.0.1", resolve));
  });

  test.afterAll(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  test.beforeEach(() => {
    keys = [jwk1];
    clearOidcKeyCacheForTests();
  });

  test("accepts a valid RS256 token and rejects unsigned/tampered tokens", async () => {
    await expect(verifyIdToken(token("key-1", pair1.privateKey), options)).resolves.toMatchObject({ sub: "subject-1" });

    const unsignedHeader = Buffer.from(JSON.stringify({ alg: "none", kid: "key-1" })).toString("base64url");
    const unsignedPayload = token("key-1", pair1.privateKey).split(".")[1];
    await expect(verifyIdToken(`${unsignedHeader}.${unsignedPayload}.x`, options)).rejects.toThrow("algorithm");

    const parts = token("key-1", pair1.privateKey).split(".");
    const tampered = `${parts[0]}.${Buffer.from(JSON.stringify({ sub: "attacker" })).toString("base64url")}.${parts[2]}`;
    await expect(verifyIdToken(tampered, options)).rejects.toThrow("signature");
  });

  test("refreshes cached JWKS once when the provider rotates signing keys", async () => {
    await verifyIdToken(token("key-1", pair1.privateKey), options);
    keys = [jwk2];
    await expect(verifyIdToken(token("key-2", pair2.privateKey), options)).resolves.toMatchObject({ sub: "subject-1" });
  });

  test("rejects valid signatures carrying invalid lifecycle claims", async () => {
    await expect(verifyIdToken(token("key-1", pair1.privateKey, { exp: 1 }), options)).rejects.toThrow("expired");
    await expect(verifyIdToken(token("key-1", pair1.privateKey, { iss: "https://wrong.example" }), options)).rejects.toThrow("issuer");
    await expect(verifyIdToken(token("key-1", pair1.privateKey, { aud: "other-client" }), options)).rejects.toThrow("audience");
    await expect(verifyIdToken(token("key-1", pair1.privateKey, { nonce: "wrong" }), options)).rejects.toThrow("nonce");
  });
});

test("IAM administration keeps an exact closed gateway boundary", () => {
  expect(resolveAllowedPath(["identity", "bindings"])).not.toBeNull();
  expect(resolveAllowedPath(["principals"])).not.toBeNull();
  expect(resolveAllowedPath(["identity", "tokens"])).toBeNull();

  expect(resolveAllowedQuery(["identity", "bindings"], new URLSearchParams("limit=25&offset=0")))
    .toBe("limit=25&offset=0");
  expect(resolveAllowedQuery(["identity", "bindings"], new URLSearchParams("limit=500&offset=0")))
    .toBeNull();
  expect(resolveAllowedQuery(["principals"], new URLSearchParams("kind=user&active=true&module=content")))
    .toBe("kind=user&active=true&module=content");
  expect(resolveAllowedQuery(["principals"], new URLSearchParams("kind=agent&active=true&module=content")))
    .toBeNull();

  expect(resolveAllowedWritePath(["identity", "bindings"])).not.toBeNull();
  expect(resolveAllowedWritePath(["identity", "bindings", "binding-1", "deactivate"])).not.toBeNull();
  expect(resolveAllowedWritePath(["identity", "bindings", "binding-1", "delete"])).toBeNull();
  expect(resolveAllowedWritePath(["principals", "khal", "roles"])).toBeNull();
});

test("OIDC internal transport preserves the canonical provider path and rejects cross-origin endpoints", () => {
  expect(providerRequestUrl(
    "http://iam.localhost:13210/oauth/v2/token?audience=workbench",
    "http://iam.localhost:13210",
    "http://caddy:13210",
  )).toBe("http://caddy:13210/oauth/v2/token?audience=workbench");
  expect(() => providerRequestUrl(
    "http://unexpected.internal/token",
    "http://iam.localhost:13210",
    "http://caddy:13210",
  )).toThrow("origin does not match issuer");
  expect(() => providerRequestUrl(
    "http://iam.localhost:13210/token",
    "http://iam.localhost:13210",
    "http://user:password@caddy:13210",
  )).toThrow("forbidden URL components");
  expect(providerRequestUrl(
    "http://iam.localhost:80/oauth/%2e%2e/token?audience=workbench",
    "http://iam.localhost",
    "http://caddy:13210/private",
  )).toBe("http://caddy:13210/private/token?audience=workbench");
  expect(providerRequestUrl(
    "http://[::1]:13210/jwks",
    "http://[::1]:13210",
    "http://[fd00::1]:13210",
  )).toBe("http://[fd00::1]:13210/jwks");
  expect(() => providerRequestUrl(
    "http://iam.localhost.:13210/token",
    "http://iam.localhost:13210",
    "http://caddy:13210",
  )).toThrow("origin does not match issuer");
  expect(() => providerRequestUrl(
    "http://user:password@iam.localhost:13210/token",
    "http://iam.localhost:13210",
    "http://caddy:13210",
  )).toThrow("forbidden URL components");
  expect(() => providerRequestUrl(
    "not-a-url",
    "http://iam.localhost:13210",
    "http://caddy:13210",
  )).toThrow("not an absolute URL");
});

test("OIDC discovery cache separates distinct internal transport routes", async () => {
  const canonicalIssuer = "http://iam.example.test";
  const document = JSON.stringify({
    issuer: canonicalIssuer,
    authorization_endpoint: `${canonicalIssuer}/authorize`,
    token_endpoint: `${canonicalIssuer}/token`,
    jwks_uri: `${canonicalIssuer}/jwks`,
  });
  let firstHits = 0;
  let secondHits = 0;
  const first = createServer((_request, response) => {
    firstHits += 1;
    response.setHeader("content-type", "application/json");
    response.end(document);
  });
  const second = createServer((_request, response) => {
    secondHits += 1;
    response.setHeader("content-type", "application/json");
    response.end(document);
  });
  const previousDevMode = process.env.TANAGHOM_DEV_MODE;
  process.env.TANAGHOM_DEV_MODE = "1";
  clearOidcDiscoveryCacheForTests();
  try {
    await Promise.all([
      new Promise<void>((resolve) => first.listen(3124, "127.0.0.1", resolve)),
      new Promise<void>((resolve) => second.listen(3125, "127.0.0.1", resolve)),
    ]);
    await discover(canonicalIssuer, "http://127.0.0.1:3124");
    await discover(canonicalIssuer, "http://127.0.0.1:3125");
    await discover(canonicalIssuer, "http://127.0.0.1:3124");
    expect({ firstHits, secondHits }).toEqual({ firstHits: 1, secondHits: 1 });
  } finally {
    clearOidcDiscoveryCacheForTests();
    if (previousDevMode == null) delete process.env.TANAGHOM_DEV_MODE;
    else process.env.TANAGHOM_DEV_MODE = previousDevMode;
    await Promise.all([
      new Promise<void>((resolve) => first.close(() => resolve())),
      new Promise<void>((resolve) => second.close(() => resolve())),
    ]);
  }
});
