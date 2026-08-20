import { expect, test } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #443 — bounded browser check for the read-only Settings-truth surface. Each state is driven by a
// CONTROLLED page.route mock (explicitly sanctioned; non-persistent, mutates no operator config): a
// populated read, an empty config, an unavailable upstream, and a typed error. The mocked payload is
// exactly the safe backend projection shape — presence/type-only secret refs and endpoints with no
// userinfo/query/fragment — so the surface can be proved to render truthfully and to leak nothing.

const SETTINGS = "**/gw/admin/settings/truth";
const SETTINGS_URL = `${WB_URL}/admin/settings`;

const POPULATED = {
  authority: "system_config (governed provider/model/route configuration) via engine.load_config",
  provenance: { available: false },
  providers: [
    {
      key: "groq",
      kind: "openai_chat",
      endpoint: "https://api.groq.com/openai/v1",
      secret_reference: { required: true, type: "env_var_reference" },
      availability: { state: "configured" },
    },
    {
      key: "ollama",
      kind: "openai_chat",
      endpoint: "http://host.docker.internal:11434/v1",
      secret_reference: { required: false, type: null },
      availability: { state: "configured" },
    },
  ],
  routes: [
    {
      role: "script",
      primary: { provider: "groq", model: "llama-3.3", availability: { state: "configured" } },
      fallback: [{ provider: "ghost", model: "nope", availability: { state: "unknown" } }],
    },
  ],
};

const json = (status: number, body: unknown) => ({
  status,
  contentType: "application/json",
  body: JSON.stringify(body),
});

test("Settings surface renders the safe projection and never leaks secrets", async ({ page }) => {
  await page.route(SETTINGS, (r) => r.fulfill(json(200, POPULATED)));
  await page.goto(SETTINGS_URL, { waitUntil: "domcontentloaded" });

  await expect(page.getByTestId("settings-admin")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("provider-groq")).toBeVisible();
  await expect(page.getByTestId("provider-ollama")).toBeVisible();
  await expect(page.getByTestId("route-script")).toBeVisible();

  // Route-role labels + availability, with the absent-provider hop failing closed to "unknown".
  await expect(page.getByTestId("route-script")).toContainText("Route role");
  await expect(page.getByTestId("route-script")).toContainText("unknown");

  // Secret references are presence/type only — no value, no env-var NAME.
  await expect(page.getByTestId("provider-secret-groq")).toContainText("required (env_var_reference)");
  await expect(page.getByTestId("provider-secret-ollama")).toContainText("not required");

  // Generation/provenance stated as unavailable, not synthesized.
  await expect(page.getByTestId("settings-authority")).toContainText("not defined by this authority");

  // Endpoints are the safe projection — no query string, fragment, or userinfo. Scoped to the
  // endpoint elements (the surrounding shell chrome legitimately contains '?'/'#').
  const groqEndpoint = await page.getByTestId("provider-endpoint-groq").innerText();
  expect(groqEndpoint).toBe("https://api.groq.com/openai/v1");
  for (const key of ["groq", "ollama"]) {
    const ep = await page.getByTestId(`provider-endpoint-${key}`).innerText();
    expect(ep).not.toContain("?");
    expect(ep).not.toContain("#");
    expect(ep).not.toContain("@");
  }
  // The Settings surface itself must leak no credential name or secret value/token shape.
  const surface = await page.getByTestId("settings-admin").innerText();
  expect(surface).not.toMatch(/API_KEY/);                    // no credential env NAME
  expect(surface).not.toMatch(/sk-or-|gsk_|Bearer /);        // no secret value/token shapes
});

test("Settings surface shows a truthful empty state", async ({ page }) => {
  await page.route(SETTINGS, (r) =>
    r.fulfill(json(200, { authority: POPULATED.authority, provenance: { available: false }, providers: [], routes: [] })));
  await page.goto(SETTINGS_URL, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("settings-admin-empty")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("settings-admin-empty")).toContainText("No providers or routes");
});

test("Settings surface surfaces an unavailable upstream truthfully", async ({ page }) => {
  await page.route(SETTINGS, (r) => r.fulfill(json(503, { detail: "tanaghom api unreachable" })));
  await page.goto(SETTINGS_URL, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("settings-admin-error")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("settings-admin-error")).toContainText("unavailable");
});

test("Settings surface surfaces a typed error truthfully", async ({ page }) => {
  await page.route(SETTINGS, (r) => r.fulfill(json(500, { detail: "read model failure" })));
  await page.goto(SETTINGS_URL, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("settings-admin-error")).toBeVisible({ timeout: 20_000 });
});

test("Settings surface is legible at desktop and narrow viewports", async ({ page }) => {
  await page.route(SETTINGS, (r) => r.fulfill(json(200, POPULATED)));
  // ONE navigation, then resize — the proper way to test responsive layout, and far lighter than
  // re-navigating per viewport (the surrounding shell re-hydrates on every navigation).
  await page.goto(SETTINGS_URL, { waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("settings-admin")).toBeVisible({ timeout: 30_000 });
  for (const vp of [{ width: 1280, height: 900 }, { width: 375, height: 812 }]) {
    await page.setViewportSize(vp);
    await expect(page.getByTestId("settings-admin")).toBeVisible();
    await expect(page.getByTestId("provider-groq")).toBeVisible();
    await expect(page.getByTestId("route-script")).toBeVisible();
    // The Settings SURFACE itself must fit its viewport (its own responsive layout — the surrounding
    // shell chrome's responsiveness is #382's concern, not this slice's).
    const overflow = await page.getByTestId("settings-admin").evaluate(
      (el, w) => Math.ceil(el.getBoundingClientRect().right) - w, vp.width);
    expect(overflow).toBeLessThanOrEqual(1);
  }
});
