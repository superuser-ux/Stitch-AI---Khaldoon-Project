import { test, expect, type Browser } from "@playwright/test";
import { reseedScheduleRound } from "./seed-schedule";

// #175 — not-assigned reviewer UX on a khal-only schedule_review gate (the live-trial case: Nour
// attempted a decision and got the raw engine error). The UI must say view-only BEFORE action,
// disable decision controls, and never show raw `approver not configured` / `not_assigned` text.
// Server-side enforcement itself is unchanged and separately proven by gates.api_selftest (#10:
// 401 unsigned, 400 actor mismatch, not_assigned denial + audit).
test.beforeEach(() => reseedScheduleRound());

const DASH = process.env.DASH_URL || "http://localhost:3000";

async function openScheduleAs(browser: Browser, reviewer: string) {
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: "tanaghom_reviewer", value: reviewer, url: DASH, httpOnly: true }]);
  const page = await ctx.newPage();
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RSCH").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-schedule").click();
  await expect(page.getByTestId("card-RSCH-1")).toBeVisible({ timeout: 20_000 });
  return { ctx, page };
}

test("Nour sees view-only guidance on the khal-only schedule gate — controls disabled, no raw error", async ({ browser }) => {
  const { ctx, page } = await openScheduleAs(browser, "nour");
  try {
    const banner = page.getByTestId("not-assigned-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/view only/i);
    await expect(banner).toContainText(/nour/i);
    await expect(banner).toContainText(/khal/i);

    // Decision controls stay visible but are disabled (per-item + batch).
    await expect(page.getByTestId("approve-RSCH-1")).toBeDisabled();
    await expect(page.getByTestId("reject-RSCH-1")).toBeDisabled();
    await expect(page.getByTestId("select-all-pending")).toBeDisabled();

    // Never raw engine text anywhere on the surface.
    await expect(page.locator("body")).not.toContainText("not configured");
    await expect(page.locator("body")).not.toContainText("not_assigned");
  } finally {
    await ctx.close();
  }
});

test("a denial that still reaches the backend (race/stale state) surfaces as client-safe guidance", async ({ browser }) => {
  // Simulate the race UI prevention can't cover: the surface loaded as assigned KHAL (controls
  // enabled), then this window is re-identified to NOUR (#170 sessionStorage persona) before the
  // click — the decide POST goes out signed as nour and the gate API rejects it (not_assigned,
  // audited). The UI must surface that denial as client-safe guidance, not raw engine text.
  const { ctx, page } = await openScheduleAs(browser, "khal");
  try {
    await expect(page.getByTestId("approve-RSCH-1")).toBeEnabled();
    await page.evaluate(() => window.sessionStorage.setItem("tanaghom-persona", "nour"));
    await page.getByTestId("approve-RSCH-1").click();

    const toast = page.getByTestId("toast");
    await expect(toast).toBeVisible({ timeout: 15_000 });
    await expect(toast).toHaveAttribute("data-kind", "err");
    await expect(toast).toContainText(/acting as/i);
    await expect(toast).not.toContainText("not configured");
    await expect(toast).not.toContainText("not_assigned");

    // The server rejected: the item is still pending for the assigned reviewer.
    await expect(page.getByTestId("card-RSCH-1")).toBeVisible();
  } finally {
    await ctx.close();
  }
});

test("Khal keeps full approval capability on the same gate", async ({ browser }) => {
  const { ctx, page } = await openScheduleAs(browser, "khal");
  try {
    await expect(page.getByTestId("not-assigned-banner")).toHaveCount(0);
    const approve = page.getByTestId("approve-RSCH-1");
    await expect(approve).toBeEnabled();
    await approve.click();
    // The immediate per-item approval commits and confirms.
    await expect(page.getByTestId("toast")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });
    await expect(page.locator("body")).not.toContainText("not configured");
  } finally {
    await ctx.close();
  }
});
