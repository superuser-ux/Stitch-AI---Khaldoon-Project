import { test, expect, type Browser, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { spawn, execSync, type ChildProcess } from "node:child_process";
import { generateKeyPairSync, sign } from "node:crypto";
import { reseed } from "./seed";
import { validateIdTokenPayload } from "../lib/iam-session";

// pure-logic: audience/authorized-party acceptance (OIDC Core 3.1.3.7 — a token merely LISTING
// this client among several audiences is not a token intended for this client unless azp says so)
test.describe("#190 ID-token audience validation (pure logic)", () => {
  const OPTS = { issuer: "https://idp.test", clientId: "tanaghom-dashboard", nonce: "n1" };
  const base = { iss: "https://idp.test", sub: "s", exp: Math.floor(Date.now() / 1000) + 300, nonce: "n1" };
  test("single audience for this client is accepted", () => {
    expect(validateIdTokenPayload({ ...base, aud: "tanaghom-dashboard" }, OPTS)).toBeNull();
  });
  test("wrong audience is rejected", () => {
    expect(validateIdTokenPayload({ ...base, aud: "someone-else" }, OPTS)).toContain("audience");
  });
  test("multi-audience WITHOUT azp is rejected", () => {
    expect(validateIdTokenPayload({ ...base, aud: ["tanaghom-dashboard", "other-app"] }, OPTS))
      .toContain("authorized party");
  });
  test("multi-audience with azp = this client is accepted", () => {
    expect(validateIdTokenPayload({ ...base, aud: ["tanaghom-dashboard", "other-app"], azp: "tanaghom-dashboard" }, OPTS)).toBeNull();
  });
  test("azp naming a different client is rejected even when we are an audience", () => {
    expect(validateIdTokenPayload({ ...base, aud: ["tanaghom-dashboard", "other-app"], azp: "other-app" }, OPTS))
      .toContain("azp");
    expect(validateIdTokenPayload({ ...base, aud: "tanaghom-dashboard", azp: "other-app" }, OPTS))
      .toContain("azp");
  });
});

// #190 (#172 S1) — flagged OIDC login + user_identity binding, end to end against a REAL
// IAM-mode dashboard instance (same build, TANAGHOM_OIDC_* env) and a minimal in-test mock OIDC
// provider (discovery, /authorize, /token — code flow with PKCE fields honored). Proves:
//   unauthenticated → sign-in surface, /gw refuses to sign (401), no persona surfaces;
//   bound login     → operates as the mapped principal through the EXISTING /gw contract;
//   unbound login   → truthful "no operating identity" (403 at /gw), never persona fallback.
// Reversibility: the default (flag-off) instance on :3000 is covered by the rest of the suite.

const IDP_PORT = 3106;
const IAM_PORT = 3107;
const ISSUER = `http://localhost:${IDP_PORT}`;
const IAM_DASH = `http://localhost:${IAM_PORT}`;
const CLIENT_ID = "tanaghom-dashboard";

const b64url = (s: string) => Buffer.from(s).toString("base64url");
const signingKey = generateKeyPairSync("rsa", { modulusLength: 2048 });
const signingJwk = {
  ...signingKey.publicKey.export({ format: "jwk" }),
  kid: "iam-login-key",
  alg: "RS256",
  use: "sig",
};

// -- minimal mock OIDC provider ------------------------------------------------------------------
let idp: Server;
let currentSub = "sub-khal";                       // which subject the next login authenticates as
const codes = new Map<string, { nonce: string; sub: string }>();

function startIdp(): Promise<void> {
  idp = createServer((req, res) => {
    const url = new URL(req.url || "/", ISSUER);
    if (url.pathname === "/.well-known/openid-configuration") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({
        issuer: ISSUER,
        authorization_endpoint: `${ISSUER}/authorize`,
        token_endpoint: `${ISSUER}/token`,
        jwks_uri: `${ISSUER}/jwks`,
      }));
      return;
    }
    if (url.pathname === "/jwks") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ keys: [signingJwk] }));
      return;
    }
    if (url.pathname === "/authorize") {
      const code = `code-${Math.random().toString(36).slice(2)}`;
      codes.set(code, { nonce: url.searchParams.get("nonce") || "", sub: currentSub });
      const redirect = new URL(url.searchParams.get("redirect_uri") || "");
      redirect.searchParams.set("code", code);
      redirect.searchParams.set("state", url.searchParams.get("state") || "");
      res.statusCode = 302;
      res.setHeader("location", redirect.toString());
      res.end();
      return;
    }
    if (url.pathname === "/token" && req.method === "POST") {
      let raw = "";
      req.on("data", (c) => { raw += c; });
      req.on("end", () => {
        const form = new URLSearchParams(raw);
        const grant = codes.get(form.get("code") || "");
        if (!grant) { res.statusCode = 400; res.end(JSON.stringify({ error: "invalid_grant" })); return; }
        const now = Math.floor(Date.now() / 1000);
        const payload = { iss: ISSUER, sub: grant.sub, aud: CLIENT_ID, exp: now + 300, iat: now,
                          nonce: grant.nonce, email: `${grant.sub}@example.test`, name: grant.sub };
        const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "iam-login-key" }));
        const encodedPayload = b64url(JSON.stringify(payload));
        const signature = sign("RSA-SHA256", Buffer.from(`${header}.${encodedPayload}`), signingKey.privateKey).toString("base64url");
        const idToken = `${header}.${encodedPayload}.${signature}`;
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify({ id_token: idToken, access_token: "at", token_type: "Bearer" }));
      });
      return;
    }
    res.statusCode = 404;
    res.end("not found");
  });
  return new Promise((resolve) => idp.listen(IDP_PORT, resolve as () => void));
}

// -- binding fixture in the dev DB ---------------------------------------------------------------
// SQL is piped via stdin (no shell interpolation of the statements; values are spec constants)
function runSql(sql: string) {
  execSync(`docker exec -i tanaghom-db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`,
    { input: sql, stdio: ["pipe", "ignore", "ignore"] });
}
function seedBinding() {
  runSql(`DELETE FROM user_identity WHERE issuer='${ISSUER}';
          INSERT INTO user_identity (issuer, subject, principal_id, created_by)
          VALUES ('${ISSUER}', 'sub-khal', 'khal', 'e2e');`);
}
function cleanupBinding() {
  runSql(`DELETE FROM user_identity WHERE issuer='${ISSUER}';`);
}

let dash: ChildProcess;

test.describe.configure({ mode: "serial" });
test.beforeAll(async () => {
  reseed();
  await startIdp();
  seedBinding();
  dash = spawn("./node_modules/.bin/next", ["start", "-p", String(IAM_PORT)], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      TANAGHOM_DEV_MODE: "1",
      API_BASE: process.env.API_BASE || "http://localhost:8009",
      TANAGHOM_OIDC_ENABLED: "1",
      TANAGHOM_OIDC_ISSUER: ISSUER,
      TANAGHOM_OIDC_CLIENT_ID: CLIENT_ID,
    },
    stdio: "ignore",
  });
  await expect(async () => {
    const res = await fetch(`${IAM_DASH}/api/runtime`);
    expect(res.ok).toBe(true);
    expect((await res.json()).identity).toBe("oidc");
  }).toPass({ timeout: 60_000 });
});
test.afterAll(async () => {
  dash?.kill("SIGTERM");
  await new Promise<void>((resolve) => idp?.close(() => resolve()));
  cleanupBinding();
});

async function freshPage(browser: Browser): Promise<Page> {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  return ctx.newPage();
}

test("IAM mode: unauthenticated gets the sign-in surface, never personas; /gw refuses to sign", async ({ browser }) => {
  const page = await freshPage(browser);
  await page.goto(`${IAM_DASH}/`);
  await expect(page.getByTestId("iam-entry")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("iam-login")).toBeVisible();
  await expect(page.getByTestId("persona-entry")).toHaveCount(0);
  const gwStatus = await page.evaluate(async () => (await fetch("/gw/rounds")).status);
  expect(gwStatus).toBe(401);
  await page.context().close();
});

test("bound login operates as the mapped principal through the existing /gw contract", async ({ browser }) => {
  currentSub = "sub-khal";
  const page = await freshPage(browser);
  await page.goto(`${IAM_DASH}/`);
  await page.getByTestId("iam-login").click();
  // mock IdP authenticates instantly and bounces back through the callback
  await page.waitForURL(`${IAM_DASH}/**`, { timeout: 30_000 });
  await expect(page.getByTestId("iam-entry")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByTestId("persona-active-badge")).toContainText(/khal/i, { timeout: 20_000 });
  // server-resolved identity flows through the EXISTING signed-principal path:
  const gw = await page.evaluate(async () => {
    const r = await fetch("/gw/me/pending-approvals");
    return { status: r.status, body: await r.json() };
  });
  expect(gw.status).toBe(200);
  // demo identity mechanisms are closed off in IAM mode:
  const reviewerPost = await page.evaluate(async () =>
    (await fetch("/api/reviewer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reviewer: "huda" }) })).status);
  expect(reviewerPost).toBe(403);
  await expect(page.locator('[data-testid="persona-entry"]')).toHaveCount(0);
  await page.context().close();
});

test("unbound login gets the truthful no-operating-identity outcome, not a fallback", async ({ browser }) => {
  currentSub = "sub-stranger";
  const page = await freshPage(browser);
  await page.goto(`${IAM_DASH}/`);
  await page.getByTestId("iam-login").click();
  await page.waitForURL(`${IAM_DASH}/**`, { timeout: 30_000 });
  await expect(page.getByTestId("iam-unbound")).toBeVisible({ timeout: 20_000 });
  // #186 — user-facing copy: plain words, no implementation/auth jargon
  await expect(page.getByTestId("iam-unbound")).toContainText("doesn't have access to Tanaghom yet");
  await expect(page.getByTestId("iam-entry")).not.toContainText(/principal|identity provider|operating identity/i);
  const gwStatus = await page.evaluate(async () => (await fetch("/gw/rounds")).status);
  expect(gwStatus).toBe(403);
  await expect(page.getByTestId("persona-entry")).toHaveCount(0);
  await expect(page.getByTestId("persona-active-badge")).toHaveCount(0);
  // sign-out returns to the sign-in surface
  await page.getByTestId("iam-signout").click();
  await expect(page.getByTestId("iam-login")).toBeVisible({ timeout: 20_000 });
  await page.context().close();
});
