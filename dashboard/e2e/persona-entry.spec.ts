import { test, expect, type Browser } from "@playwright/test";
import { reseed } from "./seed";

// #170 (#13 S1) — internal/demo persona entry + per-window persona.
// This spec opts OUT of the suite-wide established-reviewer cookie (playwright.config) to exercise
// the fresh-browser path: the entry surface appears, personas are select-only (known principals),
// each browser context holds its own persona, and the persona flows through the server-enforced
// /gw path (per-persona pending approvals resolve differently). Enforcement itself (unsigned /
// mismatched / not_assigned decide rejection) is covered by gates.api_selftest (#10).
test.use({ storageState: { cookies: [], origins: [] } });

test.beforeEach(() => reseed());

const DASH = process.env.DASH_URL || "http://localhost:3000";

async function freshPage(browser: Browser) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  return { ctx, page };
}

test("a fresh window gets the persona entry surface and enters as a known persona", async ({ page }) => {
  await page.goto("/");
  const entry = page.getByTestId("persona-entry");
  await expect(entry).toBeVisible();
  // Select-only: the surface offers known principals, no free-text actor input.
  expect(await entry.locator("input, textarea").count()).toBe(0);
  await expect(entry).toContainText("not a login");

  await entry.getByTestId("persona-option-khal").click();
  await expect(entry).toBeHidden();
  const badge = page.getByTestId("persona-active-badge");
  await expect(badge).toBeVisible();
  await expect(badge).toContainText(/khal/i);
});

test("two isolated browser contexts hold different personas, resolved per-window by the server", async ({ browser }) => {
  const a = await freshPage(browser);
  const b = await freshPage(browser);
  try {
    await a.page.goto("/");
    await a.page.getByTestId("persona-entry").getByTestId("persona-option-khal").click();
    await b.page.goto("/");
    await b.page.getByTestId("persona-entry").getByTestId("persona-option-huda").click();

    await expect(a.page.getByTestId("persona-active-badge")).toContainText(/khal/i);
    await expect(b.page.getByTestId("persona-active-badge")).toContainText(/huda/i);

    // Server-resolved proof (not just client state): /me/pending-approvals goes through the /gw
    // proxy with each window's persona header. The seeded topic gate requires user:Khal, so the
    // two windows' overview approval queues must differ.
    await a.page.getByTestId("lens-overview").click();
    const aApprovals = a.page.locator("section").filter({ hasText: "My approvals" });
    await expect(aApprovals).toContainText("RE2E");

    await b.page.getByTestId("lens-overview").click();
    const bApprovals = b.page.locator("section").filter({ hasText: "My approvals" });
    // Data-independent (the shared dev DB may hold huda-assigned gates): whatever the queue
    // contains, the server matched it for HUDA — never via khal's assignments.
    await expect(bApprovals).toContainText(/Matched via: user:Huda|No open approvals are currently assigned to huda/);
    await expect(bApprovals).not.toContainText("Matched via: user:Khal");
  } finally {
    await a.ctx.close();
    await b.ctx.close();
  }
});

test("an established reviewer session (cookie) skips the entry surface", async ({ browser }) => {
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: "tanaghom_reviewer", value: "khal", url: DASH, httpOnly: true }]);
  const page = await ctx.newPage();
  try {
    await page.goto("/");
    await expect(page.getByTestId("persona-active-badge")).toBeVisible();
    await expect(page.getByTestId("persona-entry")).toHaveCount(0);
  } finally {
    await ctx.close();
  }
});

test("a STALE trial cookie on the operator server no longer suppresses persona entry (#180)", async ({ browser }) => {
  // Before #180 this cookie alone dressed the operator surface as the locked client UI. Now the
  // server-declared surface wins: the fresh-window persona entry still appears. (The genuine
  // client-trial surface — where the entry must NOT appear — is covered by runtime-truth.spec.ts
  // against a real CLIENT_TRIAL_MODE server.)
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: "client_trial", value: "1", url: DASH }]);
  const page = await ctx.newPage();
  try {
    await page.goto("/");
    await expect(page.getByTestId("persona-entry")).toBeVisible({ timeout: 20_000 });
  } finally {
    await ctx.close();
  }
});

test("the inline reviewer switcher pins only the current window's persona", async ({ browser }) => {
  const a = await freshPage(browser);
  try {
    await a.page.goto("/");
    await a.page.getByTestId("persona-entry").getByTestId("persona-option-khal").click();
    await expect(a.page.getByTestId("persona-active-badge")).toContainText(/khal/i);

    // A second page in the SAME context shares the cookie default (khal) but its own window scope.
    const p2 = await a.ctx.newPage();
    await p2.goto("/");
    // Cookie was set by the first window's entry → established session, no gate.
    await expect(p2.getByTestId("persona-active-badge")).toContainText(/khal/i);

    // Switch p2 to huda via the inline switcher: p2 re-identifies, the first window must not.
    await p2.locator('[data-testid="persona-active-badge"]').waitFor();
    await p2.getByRole("combobox").filter({ hasText: /khal/i }).first().click();
    await p2.getByRole("option", { name: /huda/i }).click();
    await expect(p2.getByTestId("persona-active-badge")).toContainText(/huda/i);

    await a.page.reload();
    await expect(a.page.getByTestId("persona-active-badge")).toContainText(/khal/i);
  } finally {
    await a.ctx.close();
  }
});

// #215 — a response that STARTED under the superseded default persona must never overwrite the
// picked persona's authority state, no matter how late it resolves. Deterministic ordering (no
// timing luck): the pre-pick default request (no persona header) is HELD at the route layer,
// the picked persona's request resolves first and commits, then the held response is RELEASED
// and its completion is awaited — state must not change.
test("a delayed default-persona response cannot overwrite the picked persona's approvals (#215)", async ({ browser }) => {
  const { ctx, page } = await freshPage(browser);
  let releaseHeld: (() => void) | undefined;
  const held = new Promise<void>((resolve) => { releaseHeld = resolve; });
  let heldCount = 0;
  await page.route(/\/gw\/me\/pending-approvals/, async (route) => {
    const persona = route.request().headers()["x-tanaghom-persona"] || "";
    if (!persona) { heldCount++; await held; }        // the superseded default-persona request
    await route.continue();
  });
  try {
    await page.goto("/");
    await page.getByTestId("persona-entry").getByTestId("persona-option-huda").click();
    await expect(page.getByTestId("persona-active-badge")).toContainText(/huda/i);
    await page.getByTestId("lens-overview").click();
    const approvals = page.locator("section").filter({ hasText: "My approvals" });
    // the CURRENT persona's response committed while the default response is still held
    await expect(approvals).toContainText(
      /Matched via: user:Huda|No open approvals are currently assigned to huda/, { timeout: 20_000 });
    expect(heldCount).toBeGreaterThanOrEqual(1);
    // NOW release the stale response and wait for it to fully complete…
    const staleDone = page.waitForResponse((res) =>
      /\/gw\/me\/pending-approvals/.test(res.url())
      && !(res.request().headers()["x-tanaghom-persona"] || ""));
    releaseHeld!();
    await staleDone;
    // …and prove it was discarded: the picked persona's state is untouched
    await expect(approvals).toContainText(
      /Matched via: user:Huda|No open approvals are currently assigned to huda/);
    await expect(approvals).not.toContainText("Matched via: user:Khal");
  } finally {
    await ctx.close();
  }
});

// #215 (re-review) — on an actual persona TRANSITION the previous persona's authority projection
// must fail closed IMMEDIATELY, even if the new persona's authority request fails or never
// resolves. Start with khal's approvals visible, switch to huda, make huda's authority requests
// hang, and prove khal's approvals/admin are instantly absent and cannot reappear.
test("a persona transition clears prior authority even when the new persona's load fails (#215)", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  let blockHuda = false;
  const hudaHang = new Promise<void>(() => { /* never resolves while blocking */ });
  await page.route(/\/gw\/(me\/pending-approvals|principal-roles|principal-groups|approval-policies)/, async (route) => {
    const persona = route.request().headers()["x-tanaghom-persona"] || "";
    if (blockHuda && persona === "huda") { await hudaHang; return; }   // stall the new persona's authority load
    await route.continue();
  });
  try {
    await page.goto("/");
    await page.getByTestId("persona-entry").getByTestId("persona-option-khal").click();
    await page.getByTestId("lens-overview").click();
    const approvals = page.locator("section").filter({ hasText: "My approvals" });
    // khal has assigned gates in the accumulated dev DB — its authority projection is visible
    await expect(approvals).toContainText("Matched via: user:Khal", { timeout: 20_000 });

    // transition to huda, but huda's authority requests will hang
    blockHuda = true;
    await page.getByRole("combobox").filter({ hasText: /khal/i }).click();
    await page.getByRole("option").filter({ hasText: /huda/i }).click();
    await expect(page.getByTestId("persona-active-badge")).toContainText(/huda/i);

    // fail closed IMMEDIATELY: khal's approvals are gone and cannot reappear under the huda badge
    await expect(approvals).not.toContainText("Matched via: user:Khal", { timeout: 10_000 });
    // give any late khal response a chance to (wrongly) repopulate — it must not
    await page.waitForTimeout(1500);
    await expect(approvals).not.toContainText("Matched via: user:Khal");
  } finally {
    await ctx.close();
  }
});
