import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #93 / #50 — topic review cards surface the ACTUAL selected framework (its real name + component
// steps from the managed content-format registry), not just the generic format label. Presentation-
// only: a frontend join of the topic's `format` against GET /content-formats. Drives the real
// dashboard (:3000) against the RE2E topic round, whose slots carry distinct real formats:
//   RE2E-1 Hero Reel (no components) · RE2E-2 Carousel (7 steps) · RE2E-3 Pic + Caption (no components)
async function openTopicFull(page: Page, width = 1440) {
  await page.setViewportSize({ width, height: 1200 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-2")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("density-full").click();
}

test.beforeEach(() => reseed());

test("Carousel topic card surfaces the actual framework name + its component steps (#50)", async ({ page }) => {
  test.setTimeout(120_000);
  await openTopicFull(page);

  // the framework block renders for a format whose managed framework has components
  const block = page.getByTestId("framework-RE2E-2");
  await expect(block).toBeVisible();

  // it names the ACTUAL selected framework — distinct from the generic "Carousel" format label
  const name = page.getByTestId("framework-name-RE2E-2");
  await expect(name).toHaveText("Deep Transformation Carousel");
  await expect(name).not.toHaveText("Carousel");

  // all seven real component steps are surfaced (not a generic Build/Return/Close placeholder)
  const components = page.getByTestId("framework-components-RE2E-2");
  await expect(components).toContainText("Hook");
  await expect(components).toContainText("Concept Anchor");
  await expect(components).toContainText("Reflective CTA");
  const stepCount = await components.evaluate((el) => el.childElementCount);
  expect(stepCount).toBe(7);
});

test("Hero Reel topic card surfaces its managed 10-step framework (#177)", async ({ page }) => {
  test.setTimeout(120_000);
  await openTopicFull(page);

  // #177 — the Hero Reel / 60.viral.01 structure now lives in the registry (it was previously
  // keyed under the retired reel_studio name and never merged), so the framework block renders.
  const block = page.getByTestId("framework-RE2E-1");
  await expect(block).toBeVisible();
  await expect(page.getByTestId("framework-name-RE2E-1")).toHaveText("Hero Reel");
  const components = page.getByTestId("framework-components-RE2E-1");
  await expect(components).toContainText("Micro-Story");
  await expect(components).toContainText("Cognitive Flip");
  await expect(components).toContainText("Viral Ending");
  const stepCount = await components.evaluate((el) => el.childElementCount);
  expect(stepCount).toBe(10);
});

test("topic card without managed framework components degrades gracefully (#50/#177)", async ({ page }) => {
  test.setTimeout(120_000);
  await openTopicFull(page);

  // Pic + Caption is the explicit legacy format (no client framework) → no framework block,
  // no empty shell (Hero Reel used to be this test's subject before #177 fixed its registry data).
  await expect(page.getByTestId("framework-RE2E-3")).toHaveCount(0);

  // ...but the card itself is fully intact: topic content, the plain format badge, and the
  // selection affordance all remain (the new block never displaces existing card structure)
  await expect(page.getByTestId("topic-body-RE2E-3")).toBeVisible();
  await expect(page.getByTestId("card-RE2E-3")).toContainText("Pic + Caption");
  await expect(page.getByTestId("select-RE2E-3")).toBeVisible();
});
