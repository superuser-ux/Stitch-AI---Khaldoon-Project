import { test, expect, type Browser, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";
import { spawn, execSync, type ChildProcess } from "node:child_process";
import { reseed } from "./seed";

// #194 (#172 S2) — governed identity-binding administration + immediate revocation, end to end:
// a signed-in identity administrator connects/disconnects/reconnects sign-in identities through
// the bounded admin surface, and a DISCONNECTED binding blocks its live session on the very next
// authority-bearing request (no principal substitution; fresh sign-in required after reconnect).
// Same real-instance pattern as iam-login.spec.ts (own ports to avoid collision).

const IDP_PORT = 3108;
const IAM_PORT = 3109;
const ISSUER = `http://localhost:${IDP_PORT}`;
const IAM_DASH = `http://localhost:${IAM_PORT}`;
const CLIENT_ID = "tanaghom-dashboard";

const b64url = (s: string) => Buffer.from(s).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

let idp: Server;
let currentSub = "sub-khal";
const codes = new Map<string, { nonce: string; sub: string }>();

function startIdp(): Promise<void> {
  idp = createServer((req, res) => {
    const url = new URL(req.url || "/", ISSUER);
    if (url.pathname === "/.well-known/openid-configuration") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ issuer: ISSUER, authorization_endpoint: `${ISSUER}/authorize`, token_endpoint: `${ISSUER}/token` }));
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
        const grant = codes.get(new URLSearchParams(raw).get("code") || "");
        if (!grant) { res.statusCode = 400; res.end(JSON.stringify({ error: "invalid_grant" })); return; }
        const now = Math.floor(Date.now() / 1000);
        const payload = { iss: ISSUER, sub: grant.sub, aud: CLIENT_ID, exp: now + 300, iat: now, nonce: grant.nonce };
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify({ id_token: `${b64url(JSON.stringify({ alg: "none" }))}.${b64url(JSON.stringify(payload))}.x` }));
      });
      return;
    }
    res.statusCode = 404; res.end("nf");
  });
  return new Promise((resolve) => idp.listen(IDP_PORT, resolve as () => void));
}

function runSql(sql: string) {
  execSync(`docker exec -i tanaghom-db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`,
    { input: sql, stdio: ["pipe", "ignore", "ignore"] });
}

let dash: ChildProcess;
test.describe.configure({ mode: "serial" });
test.beforeAll(async () => {
  reseed();
  await startIdp();
  runSql(`DELETE FROM user_identity WHERE issuer='${ISSUER}';
          INSERT INTO user_identity (issuer, subject, principal_id, created_by)
          VALUES ('${ISSUER}', 'sub-khal', 'khal', 'e2e');`);
  dash = spawn("./node_modules/.bin/next", ["start", "-p", String(IAM_PORT)], {
    cwd: process.cwd(),
    env: { ...process.env, TANAGHOM_DEV_MODE: "1", API_BASE: process.env.API_BASE || "http://localhost:8009",
           TANAGHOM_OIDC_ENABLED: "1", TANAGHOM_OIDC_ISSUER: ISSUER, TANAGHOM_OIDC_CLIENT_ID: CLIENT_ID },
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
  runSql(`DELETE FROM user_identity WHERE issuer='${ISSUER}';`);
});

async function loginAs(browser: Browser, sub: string): Promise<Page> {
  currentSub = sub;
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await ctx.newPage();
  await page.goto(`${IAM_DASH}/`);
  await page.getByTestId("iam-login").click();
  await page.waitForURL(`${IAM_DASH}/**`, { timeout: 30_000 });
  return page;
}

test("admin connects, disconnects, and reconnects a sign-in identity through the bounded surface", async ({ browser }) => {
  test.setTimeout(180_000);
  const page = await loginAs(browser, "sub-khal");
  await page.goto(`${IAM_DASH}/admin/identity`);
  await expect(page.getByTestId("identity-admin")).toBeVisible({ timeout: 20_000 });

  // connect sub-huda -> huda (the issuer is server-declared and fixed — no free-text drift)
  await expect(page.getByTestId("binding-issuer-fixed")).toHaveText(ISSUER);
  await page.getByTestId("binding-subject").fill("sub-huda");
  await page.getByTestId("binding-principal").selectOption("huda");
  await page.getByTestId("binding-create").click();
  await expect(page.getByTestId("binding-status-sub-huda")).toHaveText("connected", { timeout: 20_000 });

  // duplicate create is an honest conflict, not an overwrite
  await page.getByTestId("binding-subject").fill("sub-huda");
  await page.getByTestId("binding-principal").selectOption("nour");
  await page.getByTestId("binding-create").click();
  await expect(page.getByTestId("identity-admin-error")).toContainText(/already exists/i);
  await expect(page.getByTestId("binding-sub-huda")).toContainText("Huda");   // unchanged target

  // disconnect (confirm-gated) then reconnect (confirm-gated)
  await page.getByTestId("binding-toggle-sub-huda").click();
  await page.getByTestId("binding-confirm-sub-huda").click();
  await expect(page.getByTestId("binding-status-sub-huda")).toHaveText("disconnected", { timeout: 20_000 });
  await page.getByTestId("binding-toggle-sub-huda").click();
  await page.getByTestId("binding-confirm-sub-huda").click();
  await expect(page.getByTestId("binding-status-sub-huda")).toHaveText("connected", { timeout: 20_000 });
  await page.context().close();
});

test("disconnecting a binding blocks its LIVE session on the next request; reconnect requires fresh sign-in", async ({ browser }) => {
  test.setTimeout(240_000);
  // huda signs in (bound by the previous test's reconnect) and can operate
  const huda = await loginAs(browser, "sub-huda");
  await expect(huda.getByTestId("persona-active-badge")).toContainText(/huda/i, { timeout: 20_000 });
  expect(await huda.evaluate(async () => (await fetch("/gw/rounds")).status)).toBe(200);

  // khal disconnects huda's sign-in link while huda's session is live
  const khal = await loginAs(browser, "sub-khal");
  await khal.goto(`${IAM_DASH}/admin/identity`);
  await expect(khal.getByTestId("binding-status-sub-huda")).toHaveText("connected", { timeout: 20_000 });
  await khal.getByTestId("binding-toggle-sub-huda").click();
  await khal.getByTestId("binding-confirm-sub-huda").click();
  await expect(khal.getByTestId("binding-status-sub-huda")).toHaveText("disconnected", { timeout: 20_000 });

  // huda's very next authority-bearing request fails closed — no principal substitution. The
  // page's own background /gw polling may have already hit the revocation (403 access-not-
  // configured + session cleared), in which case this explicit call sees 401 not-authenticated;
  // both are the truthful fail-closed outcomes, and 200 would be the violation.
  const blocked = await huda.evaluate(async () => {
    const r = await fetch("/gw/rounds");
    return { status: r.status, body: await r.json().catch(() => ({})) };
  });
  expect([401, 403]).toContain(blocked.status);
  expect(JSON.stringify(blocked.body)).toMatch(/access not configured|not authenticated/);
  // the session was invalidated: a reload lands on the sign-in surface (no demo fallback)
  await huda.reload();
  await expect(huda.getByTestId("iam-entry")).toBeVisible({ timeout: 20_000 });
  await expect(huda.getByTestId("persona-entry")).toHaveCount(0);

  // reconnecting does NOT revive the invalidated session — a fresh sign-in is required and works
  await khal.getByTestId("binding-toggle-sub-huda").click();
  await khal.getByTestId("binding-confirm-sub-huda").click();
  await expect(khal.getByTestId("binding-status-sub-huda")).toHaveText("connected", { timeout: 20_000 });
  await expect(huda.getByTestId("iam-entry")).toBeVisible();   // still signed out
  currentSub = "sub-huda";
  await huda.getByTestId("iam-login").click();
  await huda.waitForURL(`${IAM_DASH}/**`, { timeout: 30_000 });
  await expect(huda.getByTestId("persona-active-badge")).toContainText(/huda/i, { timeout: 20_000 });

  await huda.context().close();
  await khal.context().close();
});

test("pagination walks past the first page from server truth", async ({ browser }) => {
  test.setTimeout(120_000);
  runSql(`INSERT INTO user_identity (issuer, subject, principal_id, created_by)
          SELECT '${ISSUER}', 'zbulk-' || lpad(g::text, 3, '0'), 'huda', 'e2e'
          FROM generate_series(1, 30) g;`);
  try {
    const page = await loginAs(browser, "sub-khal");
    await page.goto(`${IAM_DASH}/admin/identity`);
    await expect(page.getByTestId("bindings-page-info")).toContainText(/^1–25 of /, { timeout: 20_000 });
    await page.getByTestId("bindings-next").click();
    await expect(page.getByTestId("bindings-page-info")).toContainText(/^26–/, { timeout: 20_000 });
    await expect(page.getByTestId("binding-zbulk-030")).toBeVisible();
    await page.context().close();
  } finally {
    runSql(`DELETE FROM user_identity WHERE issuer='${ISSUER}' AND subject LIKE 'zbulk-%';`);
  }
});

test("a signed-in NON-admin gets the truthful denied surface, and spoofed client state grants nothing", async ({ browser }) => {
  test.setTimeout(120_000);
  const huda = await loginAs(browser, "sub-huda");
  await huda.goto(`${IAM_DASH}/admin/identity`);
  await expect(huda.getByTestId("identity-admin-denied")).toBeVisible({ timeout: 20_000 });
  // #195 review (least privilege): the ADMIN SURFACE never requests the eligible-principal
  // selection dataset for a non-admin — measured over a clean reload of the standalone admin
  // page (the main dashboard's own reviewer-name lookup is a separate pre-existing surface).
  const principalRequests: string[] = [];
  huda.on("request", (req) => { if (req.url().includes("/gw/principals")) principalRequests.push(req.url()); });
  await huda.reload();
  await expect(huda.getByTestId("identity-admin-denied")).toBeVisible({ timeout: 20_000 });
  expect(principalRequests).toEqual([]);
  // spoofed persona header/client state grants no admin authority (server decides)
  const spoofed = await huda.evaluate(async () => {
    window.sessionStorage.setItem("tanaghom-persona", "khal");
    const r = await fetch("/gw/identity/bindings", { headers: { "x-tanaghom-persona": "khal" } });
    return r.status;
  });
  expect(spoofed).toBe(400);   // still huda (persona ignored under IAM) -> engine denies non-admin
  await huda.context().close();
});
