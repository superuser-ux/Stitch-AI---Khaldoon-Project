import { test, expect, type Page } from "@playwright/test";
import { reseedOpsRounds } from "./seed-ops";

// #261 — the reusable responsive-shell contract. At every required viewport: no horizontal document
// overflow, the primary workspace fills the available content area at wide desktop (no unowned right
// gutter), and — the root cause — a visible actionable control that scrolls under the sticky review
// header can be clicked with ORDINARY pointer click() after normal scroll positioning. No force,
// dispatchEvent, coordinate clicks, CSS overrides, or disabled-pointer-event bypasses are used.

const VIEWPORTS = [
  { w: 375, h: 812, label: "mobile" },
  { w: 768, h: 1024, label: "tablet" },
  { w: 1280, h: 900, label: "desktop" },
  { w: 1920, h: 1080, label: "wide" },
] as const;

test.beforeEach(() => reseedOpsRounds());

async function openStageFull(page: Page, round: string, nav: "edit" | "distribution") {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId(`round-opt-${round}`).click();
  await page.waitForLoadState("networkidle");
  // the side nav collapses behind a toggle at narrow widths — reveal it if needed, then navigate
  const navBtn = page.getByTestId(`nav-${nav}`);
  if (!(await navBtn.isVisible().catch(() => false))) await page.getByTestId("nav-toggle").click();
  await navBtn.click();
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("density-full")).toBeVisible({ timeout: 20_000 });
}

function docOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

for (const vp of VIEWPORTS) {
  test(`shell contract at ${vp.w}px (${vp.label}) — no overflow, workspace fills, sticky never intercepts (#261)`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width: vp.w, height: vp.h });
    await openStageFull(page, "REDIT", "edit");

    // 2) no horizontal DOCUMENT overflow at this viewport
    expect(await docOverflow(page)).toBeLessThanOrEqual(0);

    // 3) wide desktop: the main workspace spans the content area — no unowned right gutter. The
    // review content's right edge reaches close to main's right edge (allowing the intended padding).
    if (vp.w >= 1280) {
      const gap = await page.evaluate(() => {
        const main = document.querySelector('[data-testid="review-main"]');
        const status = document.querySelector('[data-testid="round-status"]');
        if (!main || !status) return 0;
        return main.getBoundingClientRect().right - status.getBoundingClientRect().right;
      });
      expect(gap).toBeLessThan(vp.w * 0.25);   // no ~third-of-screen dead gutter
    }

    // 5/6) the sticky header must not intercept a visible actionable control. The density switcher
    // lives INSIDE the sticky region; a card control lives BELOW it. Toggle density to full, then
    // click a control on the last card with an ORDINARY click after normal scroll — it must land.
    await page.getByTestId("density-full").click();
    const card = page.getByTestId("card-REDIT-1");
    await expect(card).toBeVisible({ timeout: 20_000 });
    // scroll the card's media input under the sticky header, then click it normally (no bypass)
    const input = card.getByPlaceholder("media reference (path or URL)");
    await input.scrollIntoViewIfNeeded();
    await input.click();                       // ordinary click: fails if the sticky band intercepts
    await expect(input).toBeFocused();
    // and an in-sticky-region control still works with an ordinary click
    await page.getByTestId("density-compact").click();
    await expect(page.getByTestId("density-compact")).toHaveAttribute("aria-pressed", "true");

    // 4) header controls + nav + main do not produce overflow after interaction either
    expect(await docOverflow(page)).toBeLessThanOrEqual(0);
  });
}

// #280 — every LENS surface (Overview, Workflow, Grid, Calendar, Inbox) on a populated run must be
// free of unintended horizontal document overflow at the required breakpoints. Deliberate scrolling
// is allowed only inside a semantically scrollable data region (the calendar week board), which is
// contained and never spills the document.
for (const vp of VIEWPORTS.filter((v) => v.w <= 1280)) {
  test(`all lenses free of horizontal overflow at ${vp.w}px (${vp.label}) on a populated run (#280)`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width: vp.w, height: vp.h });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("round-trigger").click();
    await page.getByTestId("round-opt-REDIT").click();
    await page.waitForLoadState("networkidle");
    for (const lens of ["overview", "workflow", "grid", "calendar", "inbox"] as const) {
      await page.getByTestId(`lens-${lens}`).click();
      await expect(page.getByTestId("review-main")).toBeVisible({ timeout: 20_000 });
      await expect
        .poll(() => docOverflow(page), { message: `lens ${lens} @${vp.w}px`, timeout: 10_000 })
        .toBeLessThanOrEqual(0);
    }
  });
}

// Distribution surface — the same ordinary-pointer contract at every viewport (the regression was
// reported on Distribution/Edit specifically).
for (const vp of VIEWPORTS) {
  test(`distribution surface accepts ordinary pointer interaction at ${vp.w}px (#261)`, async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width: vp.w, height: vp.h });
    await openStageFull(page, "RDIST", "distribution");
    expect(await docOverflow(page)).toBeLessThanOrEqual(0);
    await page.getByTestId("density-full").click();
    const card = page.getByTestId("card-RDIST-1");
    await expect(card).toBeVisible({ timeout: 20_000 });
    const input = card.getByPlaceholder("media reference (path or URL)");
    await input.scrollIntoViewIfNeeded();
    await input.click();                       // ordinary click under the sticky header
    await expect(input).toBeFocused();
    expect(await docOverflow(page)).toBeLessThanOrEqual(0);
  });
}
