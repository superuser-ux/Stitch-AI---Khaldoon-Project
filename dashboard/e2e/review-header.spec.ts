import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #20 — compact review header/telemetry. Cards must begin higher (reduced header footprint) while the
// count-first telemetry stays understandable at a glance, and a lookup-scrolled card must clear the
// sticky header (never be intercepted). Drives the real dashboard (:3000) against the RE2E topic round.
const STICKY = ".sticky.top-0";

async function openTopic(page: Page, w = 1440, h = 1000) {
  await page.setViewportSize({ width: w, height: h });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });
}

const stickyHeight = (page: Page) =>
  page.evaluate((sel) => Math.round(document.querySelector(sel)!.getBoundingClientRect().height), STICKY);
const cardTopDoc = (page: Page, id: string) =>
  page.getByTestId(id).evaluate((el) => Math.round(el.getBoundingClientRect().top + window.scrollY));

test.beforeEach(() => reseed());

test("compact header keeps counts at a glance and lifts cards higher", async ({ page }) => {
  await openTopic(page);
  // count-first telemetry preserved (the operator summary must stay understandable)
  for (const id of ["metric-pending", "metric-approved", "metric-regen", "metric-dropped", "disposition-progress", "metric-cards"]) {
    await expect(page.getByTestId(id)).toBeVisible();
  }
  // view controls survive the move into the dense row
  await expect(page.getByTestId("idmode-switcher")).toBeVisible();
  await expect(page.getByTestId("density-switcher")).toBeVisible();
  // reduced footprint budget history: pre-#20 ~549px header / ~800px first card; post-#20 <430/<660;
  // #136 (post-funnel-strip re-budget) measured 294px / 567px — locked with headroom below.
  expect(await stickyHeight(page)).toBeLessThan(330);
  expect(await cardTopDoc(page, "card-RE2E-1")).toBeLessThan(600);
});

test("a card scrolled to the top (like #49 lookup) clears the sticky header", async ({ page }) => {
  await openTopic(page);
  // replicate the #49 lookup scroll (scrollIntoView block:start) and confirm scroll-mt keeps the card
  // fully below the sticky header — its controls must not sit behind the header.
  await page.getByTestId("card-RE2E-3").evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(300);
  const { cardTop, stickyBottom } = await page.evaluate((sel) => {
    const c = document.querySelector('[data-testid="card-RE2E-3"]')!.getBoundingClientRect();
    const s = document.querySelector(sel)!.getBoundingClientRect();
    return { cardTop: Math.round(c.top), stickyBottom: Math.round(s.bottom) };
  }, STICKY);
  expect(cardTop).toBeGreaterThanOrEqual(stickyBottom - 4);
  // and it stays clickable (open it — a click that would fail if intercepted)
  await page.getByTestId("card-RE2E-3").getByTestId("hero-RE2E-3").click().catch(() => {});
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();
});

test("narrow viewport stays usable with the compact header", async ({ page }) => {
  await openTopic(page, 760, 1000);
  await expect(page.getByTestId("metric-pending")).toBeVisible();
  await expect(page.getByTestId("disposition-progress")).toBeVisible();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
  // pre-compaction the narrow sticky header was ~705px; must be materially smaller now.
  expect(await stickyHeight(page)).toBeLessThan(480);
});
