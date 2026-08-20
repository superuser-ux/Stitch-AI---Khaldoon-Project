import { test, expect, type Page } from "@playwright/test";

// #271 — default run planning (explicit operator format_mix), calendar continuity through Schedule
// approval, and a governed single-slot schedule revision. Drives the real dashboard (:3000) against
// the live API (:8009). Each test plans its own throwaway run so it never mutates shared fixtures.

async function openNewRun(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("new-run").click();
  await expect(page.getByTestId("format-mix")).toBeVisible();
}

test("a run cannot be planned until the framework mix totals days×posts_per_day (#271)", async ({ page }) => {
  await openNewRun(page);
  await page.getByTestId("days-input").fill("5");
  await page.getByTestId("ppd-input").fill("5");   // 25 slots
  await expect(page.getByTestId("run-total")).toHaveText("25");
  // an unallocated (or short) mix keeps submit disabled and the allocated total is flagged
  await expect(page.getByTestId("mix-total")).toHaveText("0");
  await expect(page.getByTestId("new-run-submit")).toBeDisabled();
  await page.getByTestId("mix-60.viral.01").fill("20");
  await expect(page.getByTestId("new-run-submit")).toBeDisabled();     // 20 ≠ 25
  // an ARBITRARY exact mix (20 / 5 / 0 — zero is valid) enables planning
  await page.getByTestId("mix-carousel.deep.01").fill("5");
  await expect(page.getByTestId("mix-total")).toHaveText("25");
  await expect(page.getByTestId("new-run-submit")).toBeEnabled();
});

async function enterScheduleCalendar(page: Page) {
  await page.getByTestId("nav-schedule").click();
  await page.getByTestId("lens-calendar").click();
  const open = page.getByTestId("open-gate");
  const cell = page.locator('[data-testid^="cal-format-"]').first();
  await expect(open.or(cell)).toBeVisible({ timeout: 20000 });
  if (await open.isVisible().catch(() => false)) await open.click();
}

test("calendar keeps all planned cells after Schedule approval + governed slot revision (#271)", async ({ page }) => {
  await openNewRun(page);
  await page.getByTestId("label-input").fill("E2E-271-continuity");
  await page.getByTestId("days-input").fill("2");
  await page.getByTestId("ppd-input").fill("2");   // 4 slots, one week, AM/PM
  await page.getByTestId("mix-60.viral.01").fill("2");
  await page.getByTestId("mix-carousel.deep.01").fill("2");
  await expect(page.getByTestId("new-run-submit")).toBeEnabled();
  await page.getByTestId("new-run-submit").click();
  await page.waitForLoadState("networkidle");

  // CONTINUITY: the schedule calendar shows ALL four positional cells (sourced from the run's complete
  // planned slot set, not the active-review subset) with each cell's format identity.
  await enterScheduleCalendar(page);
  await expect(page.locator('[data-testid^="cal-format-"]')).toHaveCount(4);
  await expect(page.getByTestId("cal-format-R-D01-AM").or(page.locator('[data-testid^="cal-format-"]').first()))
    .toContainText(/Hero Reel|Carousel/);
  const firstId = (await page.locator('[data-testid^="cal-format-"]').first().getAttribute("data-testid"))!
    .replace("cal-format-", "");

  // GOVERNED REVISION (incl. #278 P1): the control offers the FULL pinned eligibility set, so an
  // operator can revise a slot to a pinned-eligible framework whose original allocation was ZERO
  // ("3sec…" was allocated 0 here). Revise that slot to it + topic guidance -> the server returns ONLY
  // that slot to Schedule review under the existing reviewer authority (returned-to-review toast).
  await page.getByTestId(`revise-${firstId}`).click();
  // #278 P1 — the day input is bounded to the run's configured period (2 days here), so a revision
  // can never move a slot off the calendar; the server enforces the same 1..period_len_days range.
  await expect(page.getByTestId(`revise-day-${firstId}`)).toHaveAttribute("max", "2");
  const fmtSel = page.getByTestId(`revise-format-${firstId}`);
  const zeroOpt = await fmtSel.locator("option", { hasText: /3sec/i }).getAttribute("value");
  expect(zeroOpt).toBeTruthy();          // the zero-count, pinned-eligible framework IS offered
  await fmtSel.selectOption(zeroOpt!);
  await page.getByTestId(`revise-guidance-${firstId}`).fill("Lead with the boundary reframe");
  await page.getByTestId(`revise-submit-${firstId}`).click();
  await expect(page.getByTestId("toast")).toContainText(/returned to Schedule review/i, { timeout: 15000 });
  // continuity holds through the revision — every planned cell is still present, none duplicated/lost —
  // and the revised cell now carries the newly-selected zero-count framework.
  await expect(page.locator('[data-testid^="cal-format-"]')).toHaveCount(4);
  await expect(page.getByTestId(`cal-format-${firstId}`)).toContainText(/3sec/i);

  // narrow viewport: the planning/calendar surface stays readable with no horizontal overflow at 375px
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.locator('[data-testid^="cal-format-"]').first()).toBeVisible();
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("run-level format mix can be revised through the planning surface before approval (#278 P1)", async ({ page }) => {
  await openNewRun(page);
  await page.getByTestId("label-input").fill("E2E-271-runmix");
  await page.getByTestId("days-input").fill("2");
  await page.getByTestId("ppd-input").fill("2");   // 4 slots
  await page.getByTestId("mix-60.viral.01").fill("2");
  await page.getByTestId("mix-carousel.deep.01").fill("2");   // 3sec framework allocated ZERO
  await expect(page.getByTestId("new-run-submit")).toBeEnabled();
  await page.getByTestId("new-run-submit").click();
  await page.waitForLoadState("networkidle");

  await enterScheduleCalendar(page);
  await expect(page.locator('[data-testid^="cal-format-"]')).toHaveCount(4);
  // no 3sec cell yet — that framework was allocated zero at planning
  await expect(page.locator('[data-testid^="cal-format-"]', { hasText: /3sec/i })).toHaveCount(0);

  // #278 P1 — revise the RUN-level mix through the planning surface to include the zero-count framework.
  // Exact-total gating enforces the 4-slot total; only uncommitted (RESERVED) slots are reconciled.
  await page.getByTestId("run-mix-open").click();
  await page.getByTestId("run-mix-60.viral.01").fill("1");
  await page.getByTestId("run-mix-carousel.deep.01").fill("1");
  await page.getByTestId("run-mix-15.viral.01").fill("2");
  await expect(page.getByTestId("run-mix-total")).toHaveText("4");
  await page.getByTestId("run-mix-submit").click();
  await expect(page.getByTestId("toast")).toContainText(/Run mix updated/i, { timeout: 15000 });

  // the reconciled calendar now carries the newly-allocated framework, still exactly 4 cells (continuity)
  await expect(page.locator('[data-testid^="cal-format-"]')).toHaveCount(4);
  await expect(page.locator('[data-testid^="cal-format-"]', { hasText: /3sec/i }).first()).toBeVisible();

  // narrow viewport: the planning control + calendar stay within the viewport (no horizontal overflow).
  // Poll (web-first, not a test retry) so a transient post-resize reflow settles deterministically.
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.locator('[data-testid^="cal-format-"]').first()).toBeVisible();
  await expect.poll(async () => page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth),
    { timeout: 5000 }).toBeLessThanOrEqual(0);
});
