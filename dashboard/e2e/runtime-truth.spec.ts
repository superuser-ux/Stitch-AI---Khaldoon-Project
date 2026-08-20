import { test, expect } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { reseed } from "./seed";

// #180 — runtime-mode truth + stale-state resilience.
// The SERVER declares which surface it serves; stale Tanaghom browser state (a leftover
// client_trial cookie from a trial surface on the same host) can no longer dress the operator
// surface as the locked client UI, a visible badge self-identifies surface/writer/build, and a
// scoped reset clears ONLY Tanaghom-owned local state. Genuine client-trial mode is validated
// against a real CLIENT_TRIAL_MODE server instance.
test.beforeEach(() => reseed());

const DASH = process.env.DASH_URL || "http://localhost:3000";
const TRIAL_PORT = 3105;

test("stale client_trial cookie cannot suppress operator controls when the server is operator (#180)", async ({ browser }) => {
  const ctx = await browser.newContext();
  await ctx.addCookies([
    { name: "client_trial", value: "1", url: DASH },
    { name: "tanaghom_reviewer", value: "khal", url: DASH, httpOnly: true },
  ]);
  const page = await ctx.newPage();
  try {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // Operator controls present despite the stale trial cookie:
    await expect(page.getByTitle("Start a new run")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("persona-active-badge")).toBeVisible();
    // The badge states the server-declared surface…
    await expect(page.getByTestId("runtime-surface")).toHaveText("operator/internal");
    // …and the operator middleware actively cleared the stale cookie.
    const cookies = await ctx.cookies(DASH);
    expect(cookies.find((c) => c.name === "client_trial")).toBeUndefined();
  } finally {
    await ctx.close();
  }
});

test("the runtime badge renders surface, writer mode, and build identifier (#180)", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("runtime-badge")).toBeVisible();
  await expect(page.getByTestId("runtime-surface")).toHaveText("operator/internal");
  // the suite runs with the stub writer; sourced from the existing /health read model
  await expect(page.getByTestId("runtime-writer")).toHaveText("stub writer", { timeout: 20_000 });
  const build = await page.getByTestId("runtime-build").innerText();
  expect(build).not.toBe("…");
  expect(build).not.toBe("unknown");
  expect(build.length).toBeGreaterThanOrEqual(7);
});

test("reset clears ONLY Tanaghom-owned local/session state and recovers a fresh view (#180)", async ({ browser }) => {
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: "tanaghom_reviewer", value: "khal", url: DASH, httpOnly: true }]);
  const page = await ctx.newPage();
  try {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => {
      window.localStorage.setItem("tanaghom-view", "grid");
      window.localStorage.setItem("unrelated-app-key", "must-survive");
      window.sessionStorage.setItem("tanaghom-persona", "khal");
      window.sessionStorage.setItem("unrelated-session-key", "must-survive");
    });
    await page.getByTestId("reset-local-state").click();
    // the reset ends in location.reload(): wait for the post-reset marker (the fresh persona
    // entry) BEFORE touching the page context, so the evaluate below can never race the reload
    await expect(page.getByTestId("persona-entry")).toBeVisible({ timeout: 20_000 });

    const state = await page.evaluate(() => ({
      tanaghomLocal: Object.keys(window.localStorage).filter((k) => k.startsWith("tanaghom")),
      tanaghomSession: Object.keys(window.sessionStorage).filter((k) => k.startsWith("tanaghom")),
      foreignLocal: window.localStorage.getItem("unrelated-app-key"),
      foreignSession: window.sessionStorage.getItem("unrelated-session-key"),
    }));
    // Tanaghom-owned state gone (aside from anything freshly re-written after reload)…
    expect(state.tanaghomSession).toEqual([]);
    expect(state.tanaghomLocal.filter((k) => k === "tanaghom-view" || k === "tanaghom-persona")).toEqual([]);
    // …unrelated data untouched.
    expect(state.foreignLocal).toBe("must-survive");
    expect(state.foreignSession).toBe("must-survive");
    // Reviewer cookie cleared server-side → the window recovered to the fresh persona entry.
    await expect(page.getByTestId("persona-entry")).toBeVisible({ timeout: 20_000 });
  } finally {
    await ctx.close();
  }
});

test("the genuine client-trial surface stays locked and clearly labeled (#180 regression)", async ({ browser }) => {
  test.setTimeout(180_000);
  // A REAL trial-mode server from the same build: CLIENT_TRIAL_MODE=true on its own port.
  const child: ChildProcess = spawn(
    "./node_modules/.bin/next",
    ["start", "-p", String(TRIAL_PORT)],
    {
      cwd: process.cwd(),
      env: { ...process.env, CLIENT_TRIAL_MODE: "true", TANAGHOM_DEV_MODE: "1", API_BASE: process.env.API_BASE || "http://localhost:8009" },
      stdio: "ignore",
    },
  );
  try {
    await expect(async () => {
      const res = await fetch(`http://localhost:${TRIAL_PORT}/api/runtime`);
      expect(res.ok).toBe(true);
      expect((await res.json()).surface).toBe("client-trial");
    }).toPass({ timeout: 60_000 });

    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    await page.goto(`http://localhost:${TRIAL_PORT}/`);
    await page.waitForLoadState("networkidle");
    // Locked: no operator controls, no persona entry/badge; labeled as the client trial.
    await expect(page.getByTestId("runtime-surface")).toHaveText("client trial", { timeout: 20_000 });
    await expect(page.getByTitle("Start a new run")).toHaveCount(0);
    await expect(page.getByTestId("persona-entry")).toHaveCount(0);
    await expect(page.getByTestId("persona-active-badge")).toHaveCount(0);
    // Server-side route block intact: /admin bounces to the dashboard.
    await page.goto(`http://localhost:${TRIAL_PORT}/admin/methodology`);
    await page.waitForLoadState("networkidle");
    expect(new URL(page.url()).pathname).toBe("/");
    await ctx.close();
  } finally {
    child.kill("SIGTERM");
  }
});

// #205 — the tested build reference must be DIRECTLY visible at every viewport (no hover/menu).
// Below md a compact `build <sha>` indicator (same /api/runtime state) carries the reference and
// the scoped reset action; md+ keeps the full surface/writer/build identity. Exact text is
// asserted against the live /api/runtime response — never a baked or client-generated value.
test.describe("#205 — build reference visible at every viewport", () => {
  async function serverBuild(page: import("@playwright/test").Page) {
    return (await (await page.request.get(`${DASH}/api/runtime`)).json()).build as string;
  }

  for (const [w, h] of [[375, 700], [700, 900]] as const) {
    test(`compact build indicator + intact controls at ${w}px (normal state)`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      await page.goto("/");
      await page.waitForLoadState("networkidle");
      const expected = await serverBuild(page);
      await expect(page.getByTestId("runtime-badge-compact")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("runtime-build-compact")).toHaveText(expected);
      await expect(page.getByTestId("reset-local-state-compact")).toBeVisible();
      // primary controls stay reachable — no overflow/clipping/loss
      await expect(page.getByTestId("new-run")).toBeVisible();
      await expect(page.getByTestId("persona-active-badge")).toBeVisible();
      await expect(page.getByTestId("assistant-toggle")).toBeVisible();
      expect(await page.evaluate(() => document.body.scrollWidth
        - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    });
  }

  for (const [w, h] of [[768, 900], [1280, 800]] as const) {
    test(`full runtime identity at ${w}px; compact indicator yields to it`, async ({ page }) => {
      await page.setViewportSize({ width: w, height: h });
      await page.goto("/");
      await page.waitForLoadState("networkidle");
      const expected = await serverBuild(page);
      await expect(page.getByTestId("runtime-badge")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("runtime-build")).toHaveText(expected);
      await expect(page.getByTestId("runtime-badge-compact")).toBeHidden();
    });
  }

  test.describe("persona-entry state (fresh window, no persona chosen)", () => {
    test.use({ storageState: { cookies: [], origins: [] } });
    test("build reference visible at 375px and desktop before any persona is picked", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 700 });
      await page.goto("/");
      await page.waitForLoadState("networkidle");
      const expected = await serverBuild(page);
      await expect(page.getByTestId("persona-entry")).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("runtime-badge-compact")).toBeVisible();
      await expect(page.getByTestId("runtime-build-compact")).toHaveText(expected);
      await page.setViewportSize({ width: 1280, height: 800 });
      await expect(page.getByTestId("runtime-badge")).toBeVisible();
      await expect(page.getByTestId("runtime-build")).toHaveText(expected);
    });
  });
});
