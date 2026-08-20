import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #91 / #54 — Arabic/RTL review-card readability. Presentation-only: the Arabic topic body + rationale
// render right-to-left with roomy Arabic line-height and clean wrapping; the card holds up at a narrow
// width without horizontal overflow. Drives the real dashboard (:3000) against the RE2E topic round.
async function openTopicFull(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("density-full").click();
}

test.beforeEach(() => reseed());

test("Arabic topic body renders RTL with roomy Arabic prose line-height (#54)", async ({ page }) => {
  test.setTimeout(120_000);
  await openTopicFull(page);
  const body = page.getByTestId("topic-body-RE2E-1");
  await expect(body).toBeVisible();
  await expect(body).toHaveAttribute("dir", "auto");
  await expect(body).toHaveClass(/ar-body/);
  const style = await body.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { direction: cs.direction, lineHeight: parseFloat(cs.lineHeight), fontSize: parseFloat(cs.fontSize), overflowWrap: cs.overflowWrap };
  });
  expect(style.direction).toBe("rtl");                       // dir="auto" resolves RTL for Arabic content
  expect(style.lineHeight).toBeGreaterThan(style.fontSize * 1.5);  // leading-7 roominess, not cramped text-sm
  expect(style.overflowWrap).toBe("anywhere");               // mixed English/URLs/hashtags wrap cleanly
  // the Arabic hook hero column is RTL too
  const heroDir = await page.getByTestId("hero-RE2E-1").evaluate((el) => getComputedStyle(el).direction);
  expect(heroDir).toBe("rtl");
});

test("review card content stays within a narrow viewport — Arabic body wraps, no h-overflow (#54)", async ({ page }) => {
  test.setTimeout(120_000);
  await openTopicFull(page, 700);
  const card = page.getByTestId("card-RE2E-1");
  await expect(card).toBeVisible();
  const overflow = await card.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);                   // no meaningful horizontal overflow
  await expect(page.getByTestId("topic-body-RE2E-1")).toBeVisible();
});
