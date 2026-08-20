import { expect, test, type Browser, type Page } from "@playwright/test";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import { createHmac, generateKeyPairSync, sign } from "node:crypto";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const IDP_PORT = 3120;
const INTERNAL_IDP_PORT = 3123;
const API_PORT = 3121;
const WORKBENCH_PORT = 3122;
const ISSUER = `http://localhost:${IDP_PORT}`;
const INTERNAL_IDP = `http://127.0.0.1:${INTERNAL_IDP_PORT}`;
const WORKBENCH = `http://localhost:${WORKBENCH_PORT}`;
const CLIENT_ID = "tanaghom-workbench";
const PROXY_SECRET = "iam-workbench-test-proxy-secret";
const keyPair = generateKeyPairSync("rsa", { modulusLength: 2048 });
const publicJwk = { ...keyPair.publicKey.export({ format: "jwk" }), kid: "wb-key", alg: "RS256", use: "sig" };

let subject = "subject-bound";
let bindingActive = true;
let idp: Server;
let internalIdp: Server;
let api: Server;
let app: ChildProcess;
let secretDirectory = "";
let observedTokenRequest: URLSearchParams | null = null;
let observedPostLogoutRedirect = "";
const internalProviderPaths: string[] = [];
const codes = new Map<string, { nonce: string; subject: string }>();

function signedToken(nonce: string, sub: string) {
  const now = Math.floor(Date.now() / 1000);
  const header = Buffer.from(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "wb-key" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    iss: ISSUER,
    sub,
    aud: CLIENT_ID,
    nonce,
    iat: now,
    exp: now + 300,
    name: "Provider display hint",
    roles: ["provider-admin"],
  })).toString("base64url");
  const signature = sign("RSA-SHA256", Buffer.from(`${header}.${payload}`), keyPair.privateKey).toString("base64url");
  return `${header}.${payload}.${signature}`;
}

function proxySignature(principal: string) {
  return createHmac("sha256", PROXY_SECRET).update(principal, "utf8").digest("hex");
}

async function listen(server: Server, port: number) {
  await new Promise<void>((resolve) => server.listen(port, resolve));
}

async function close(server: Server | undefined) {
  if (!server) return;
  await new Promise<void>((resolve) => server.close(() => resolve()));
}

async function freshPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  return context.newPage();
}

test.describe("V2 cryptographic IAM and Tanaghom authority boundary", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async () => {
    const idpHandler = (internal: boolean) => (request: IncomingMessage, response: ServerResponse) => {
      const url = new URL(request.url || "/", ISSUER);
      if (internal) internalProviderPaths.push(url.pathname);
      if (url.pathname === "/.well-known/openid-configuration") {
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({
          issuer: ISSUER,
          authorization_endpoint: `${ISSUER}/authorize`,
          token_endpoint: `${ISSUER}/token`,
          jwks_uri: `${ISSUER}/jwks`,
          end_session_endpoint: `${ISSUER}/logout`,
        }));
        return;
      }
      if (url.pathname === "/jwks") {
        response.setHeader("content-type", "application/json");
        response.end(JSON.stringify({ keys: [publicJwk] }));
        return;
      }
      if (url.pathname === "/authorize") {
        const code = `code-${Math.random().toString(36).slice(2)}`;
        codes.set(code, { nonce: url.searchParams.get("nonce") || "", subject });
        const redirect = new URL(url.searchParams.get("redirect_uri") || "");
        redirect.searchParams.set("code", code);
        redirect.searchParams.set("state", url.searchParams.get("state") || "");
        response.statusCode = 302;
        response.setHeader("location", redirect.toString());
        response.end();
        return;
      }
      if (url.pathname === "/token" && request.method === "POST") {
        let body = "";
        request.on("data", (chunk) => { body += chunk; });
        request.on("end", () => {
          observedTokenRequest = new URLSearchParams(body);
          const grant = codes.get(observedTokenRequest.get("code") || "");
          if (!grant) { response.statusCode = 400; response.end(); return; }
          response.setHeader("content-type", "application/json");
          response.end(JSON.stringify({ id_token: signedToken(grant.nonce, grant.subject) }));
        });
        return;
      }
      if (url.pathname === "/logout") {
        observedPostLogoutRedirect = url.searchParams.get("post_logout_redirect_uri") || "";
        response.statusCode = 302;
        response.setHeader("location", url.searchParams.get("post_logout_redirect_uri") || WORKBENCH);
        response.end();
        return;
      }
      response.statusCode = 404;
      response.end();
    };
    idp = createServer(idpHandler(false));
    internalIdp = createServer(idpHandler(true));

    api = createServer((request, response) => {
      const url = new URL(request.url || "/", `http://127.0.0.1:${API_PORT}`);
      const asserted = request.headers["x-principal-id"] as string | undefined;
      const signature = request.headers["x-principal-signature"] as string | undefined;
      const trusted = asserted && signature === proxySignature(asserted);
      response.setHeader("content-type", "application/json");
      if (url.pathname === "/identity/binding") {
        if (!trusted || asserted !== "system") { response.statusCode = 401; response.end("{}"); return; }
        const sub = url.searchParams.get("subject");
        response.end(JSON.stringify({
          principal_id: sub === "subject-bound" && bindingActive ? "khal" : null,
          display_name_en: sub === "subject-bound" ? "Khal" : null,
        }));
        return;
      }
      if (url.pathname === "/identity/bindings" && request.method === "GET") {
        if (!trusted || asserted !== "khal") { response.statusCode = 403; response.end("{}"); return; }
        response.end(JSON.stringify({ bindings: [{
          identity_id: "binding-1",
          issuer: ISSUER,
          subject: "subject-bound",
          principal_id: "khal",
          email: null,
          active: true,
          principal_display_name_en: "Khal",
          principal_active: true,
        }], total: 1, limit: 100, offset: 0 }));
        return;
      }
      if (url.pathname === "/principals" && request.method === "GET") {
        if (!trusted || asserted !== "khal") { response.statusCode = 403; response.end("{}"); return; }
        response.end(JSON.stringify([{ principal_id: "khal", display_name_en: "Khal" }]));
        return;
      }
      if (url.pathname === "/rounds" && request.method === "POST") {
        response.end(JSON.stringify({ principal_id: trusted ? asserted : null }));
        return;
      }
      if (url.pathname === "/rounds") { response.end("[]"); return; }
      if (url.pathname === "/workflow-stages/active-enabled") {
        response.end(JSON.stringify({ version_id: "v1", version_no: 1, status: "active", stages: [] }));
        return;
      }
      if (url.pathname === "/health") { response.end(JSON.stringify({ ok: true })); return; }
      response.statusCode = 404;
      response.end("{}");
    });

    await Promise.all([listen(idp, IDP_PORT), listen(internalIdp, INTERNAL_IDP_PORT), listen(api, API_PORT)]);
    secretDirectory = mkdtempSync(join(tmpdir(), "tanaghom-iam-"));
    const sessionSecretFile = join(secretDirectory, "iam_session_secret");
    writeFileSync(sessionSecretFile, "iam-workbench-session-secret");
    chmodSync(sessionSecretFile, 0o400);
    // Match the container listener. Callback redirects must still use the configured public origin.
    app = spawn("./node_modules/.bin/next", ["start", "-p", String(WORKBENCH_PORT), "-H", "0.0.0.0"], {
      cwd: process.cwd(),
      env: {
        ...process.env,
        TANAGHOM_DEV_MODE: "1",
        TANAGHOM_OIDC_ENABLED: "1",
        TANAGHOM_OIDC_ISSUER: ISSUER,
        TANAGHOM_OIDC_INTERNAL_BASE_URL: INTERNAL_IDP,
        TANAGHOM_OIDC_CLIENT_ID: CLIENT_ID,
        TANAGHOM_OIDC_REDIRECT_URI: `${WORKBENCH}/api/auth/callback`,
        TANAGHOM_OIDC_POST_LOGOUT_REDIRECT_URI: `${WORKBENCH}/`,
        TANAGHOM_SESSION_SECRET: "",
        TANAGHOM_SESSION_SECRET_FILE: sessionSecretFile,
        TANAGHOM_SESSION_SECRET_FILE_MAX_AGE_SECONDS: "900",
        REVIEWER_PROXY_SECRET: PROXY_SECRET,
        REVIEWER_PROXY_SECRET_FILE: "",
        API_BASE: `http://127.0.0.1:${API_PORT}`,
      },
      stdio: "ignore",
    });
    await expect(async () => {
      const response = await fetch(`${WORKBENCH}/api/runtime`).catch(() => null);
      expect(response?.ok).toBe(true);
      expect((await response?.json()).identity).toBe("oidc");
    }).toPass({ timeout: 30_000 });
  });

  test.afterAll(async () => {
    app?.kill("SIGTERM");
    await Promise.all([close(idp), close(internalIdp), close(api)]);
    if (secretDirectory) rmSync(secretDirectory, { recursive: true, force: true });
  });

  test.beforeEach(() => {
    subject = "subject-bound";
    bindingActive = true;
    observedTokenRequest = null;
    observedPostLogoutRedirect = "";
    internalProviderPaths.length = 0;
  });

  test("signs only the bound Tanaghom principal; provider roles grant nothing", async ({ browser }) => {
    const page = await freshPage(browser);
    await page.goto(WORKBENCH);
    await expect(page.getByTestId("iam-login")).toBeVisible();
    await page.getByTestId("iam-login").click();
    await expect(page).toHaveURL(`${WORKBENCH}/`);
    await expect(page.getByTestId("iam-account")).toContainText("Khal");
    expect(observedTokenRequest?.get("client_secret")).toBeNull();
    expect(observedTokenRequest?.get("client_id")).toBe(CLIENT_ID);
    expect(observedTokenRequest?.get("redirect_uri")).toBe(`${WORKBENCH}/api/auth/callback`);
    expect(observedTokenRequest?.get("code_verifier")).toBeTruthy();
    expect(internalProviderPaths).toEqual(expect.arrayContaining([
      "/.well-known/openid-configuration",
      "/token",
      "/jwks",
    ]));
    expect(internalProviderPaths).not.toContain("/authorize");
    const result = await page.evaluate(async () => {
      const response = await fetch("/gw/rounds", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({}),
      });
      return { status: response.status, body: await response.json() };
    });
    expect(result).toEqual({ status: 200, body: { principal_id: "khal" } });
    await page.context().close();
  });

  test("uses the exact configured post-logout return for the public client", async ({ browser }) => {
    const page = await freshPage(browser);
    await page.goto(WORKBENCH);
    await page.getByTestId("iam-login").click();
    await expect(page.getByTestId("iam-account")).toBeVisible();
    await page.getByTestId("iam-signout").click();
    await expect.poll(() => observedPostLogoutRedirect).toBe(`${WORKBENCH}/`);
    expect(internalProviderPaths).not.toContain("/logout");
    await expect(page).toHaveURL(`${WORKBENCH}/`);
    await expect(page.getByTestId("iam-login")).toBeVisible();
    await page.context().close();
  });

  test("an authenticated but unbound identity remains fail-closed", async ({ browser }) => {
    subject = "subject-unbound";
    const page = await freshPage(browser);
    await page.goto(WORKBENCH);
    await page.getByTestId("iam-login").click();
    await expect(page.getByTestId("iam-unbound")).toContainText("not connected");
    const status = await page.evaluate(async () => (await fetch("/gw/rounds")).status);
    expect(status).toBe(403);
    await page.context().close();
  });

  test("binding deactivation revokes an existing session on its next gateway action", async ({ browser }) => {
    const page = await freshPage(browser);
    await page.goto(WORKBENCH);
    await page.getByTestId("iam-login").click();
    await expect(page.getByTestId("iam-account")).toBeVisible();
    bindingActive = false;
    const status = await page.evaluate(async () => (await fetch("/gw/rounds")).status);
    expect(status).toBe(403);
    await page.reload();
    await expect(page.getByTestId("iam-login")).toBeVisible();
    await page.context().close();
  });

  test("exposes audited identity bindings without exposing IdP authority controls", async ({ browser }) => {
    const page = await freshPage(browser);
    await page.goto(WORKBENCH);
    await page.getByTestId("iam-login").click();
    await expect(page.getByTestId("iam-account")).toBeVisible();
    await page.getByTestId("identity-admin-link").click();
    await expect(page.getByTestId("identity-admin")).toContainText("Sign-in connections");
    await expect(page.getByTestId("binding-subject-bound")).toContainText("Khal");
    await expect(page.getByTestId("identity-admin")).not.toContainText(/provider-admin|grant role|assign capability/i);
    await page.context().close();
  });
});
