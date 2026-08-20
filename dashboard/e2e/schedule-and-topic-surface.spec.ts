import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { allocateFullMix } from "./plan-helpers";

async function gotoRE2E(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
}

async function enterActiveReview(page: Page) {
  const open = page.getByTestId("open-gate");
  const anyCard = page.locator("input[type='checkbox'][data-testid^='select-']").first();
  // #76 — the gate affordance (and its slots) can render a beat after a run is created, and
  // networkidle does not cover the surface's client-side load. An instant isVisible() check here
  // raced that load and silently skipped opening the gate, leaving an empty board (the flake).
  // Wait until the surface settles into EITHER "gate needs opening" or "cards already shown".
  await expect(open.or(anyCard)).toBeVisible({ timeout: 20000 });
  if (await open.isVisible().catch(() => false)) {
    await open.click();
  }
}

test.beforeEach(() => reseed());

test("schedule stage shows code and content type before topic generation", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("new-run").click();
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill("2");
  await expect(page.getByTestId("run-total")).toHaveText("2");
  await allocateFullMix(page);
  await page.getByTestId("new-run-submit").click();

  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("generate-action")).toHaveCount(0);

  await enterActiveReview(page);
  // #76 — the schedule board's slots load asynchronously after the run is created; wait for a
  // materialized schedule card (a real select checkbox) before asserting board content, so the
  // assertions don't race an empty "0 pending" board (the source of the prior timing flake).
  await expect(page.locator("input[type='checkbox'][data-testid^='select-']").first()).toBeVisible({ timeout: 20000 });
  const main = page.getByRole("main");
  await expect(main).toContainText(/schedule board aligned to the client reference/i);
  await expect(main).toContainText(/schedule code/i);
  await expect(main).toContainText(/hero reel|carousel|pic \+ caption|3sec reel \+ caption/i);
  await expect(main).not.toContainText(/request change/i);
  await expect(main).toContainText(/approve/i);
  await expect(main).toContainText(/drop/i);

  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await expect(page.getByTestId("toast")).toContainText(/decisions submitted/i);

  await page.getByTestId("nav-topic").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("disposition-bar")).toContainText(/ready to generate/i);
});

test("topic stage shows topic code, assigned framework, and inline rework actions", async ({ page }) => {
  await gotoRE2E(page);
  await page.getByTestId("nav-topic").click();
  await enterActiveReview(page);

  const card = page.getByTestId("card-RE2E-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/topic code/i);
  await expect(card).toContainText(/framework:/i);
  await expect(card).toContainText(/lens:/i);
  await expect(card).toContainText(/approve/i);
  await expect(card).toContainText(/request change/i);
  await expect(card).toContainText(/drop \(recoverable\)/i);
});

test("approved schedule allocation preserves the same code and framework through topic and script", async ({ page }) => {
  await page.goto("/");

  await page.getByTestId("new-run").click();
  await page.getByTestId("label-input").fill("schedule-framework-chain");
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill("2");
  await expect(page.getByTestId("run-total")).toHaveText("2");
  await allocateFullMix(page);
  await page.getByTestId("new-run-submit").click();

  await page.waitForLoadState("networkidle");
  await enterActiveReview(page);
  // #76 — wait for the schedule board to materialize (a real card) BEFORE interacting: the code-display
  // switcher only renders once slots are loaded, so clicking it earlier raced the async board load.
  const firstScheduleCheckbox = page.locator("input[type='checkbox'][data-testid^='select-']").first();
  await expect(firstScheduleCheckbox).toBeVisible({ timeout: 15000 });
  await page.getByTestId("idmode-expanded").click();

  const checkboxLabel = (await firstScheduleCheckbox.getAttribute("aria-label")) || "";
  const contentCode = (checkboxLabel.match(/P\d{2}-HS\d{2}-\d{2}\.\d{2}/) || [])[0] || "";
  const scheduleCellText = await firstScheduleCheckbox.evaluate((node) => {
    let el = node.parentElement;
    while (el && el.tagName !== "TD") el = el.parentElement;
    return el?.textContent || "";
  });
  const formatName = (scheduleCellText.match(/Hero Reel|Carousel|Pic \+ Caption|3sec Reel \+ Caption/i) || [])[0] || "";
  expect(contentCode).toMatch(/^P\d{2}-HS\d{2}-\d{2}\.\d{2}$/);
  expect(formatName).toMatch(/Hero Reel|Carousel|Pic \+ Caption|3sec Reel \+ Caption/i);

  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await expect(page.getByTestId("toast")).toContainText(/decisions submitted/i);

  await page.getByTestId("nav-topic").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  // Normal generation surfaces the "Start review" control (two-stage flow); enter the review before
  // asserting the topic cards, consistent with the other generation specs.
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await enterActiveReview(page);
  await expect(page.getByRole("main")).toContainText(/topic code/i, { timeout: 20000 });

  const topicCard = page.locator("[data-testid^=card-]").filter({ hasText: contentCode }).first();
  await expect(topicCard).toBeVisible({ timeout: 20000 });
  await expect(topicCard).toContainText(formatName);

  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await expect(page.getByTestId("toast")).toContainText(/decisions submitted/i);

  await page.getByTestId("nav-script").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  // Same two-stage flow as the topic stage: enter the review before asserting the script cards.
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await enterActiveReview(page);
  await expect(page.getByRole("main")).toContainText(/script code/i, { timeout: 20000 });

  const scriptCard = page.locator("[data-testid^=card-]").filter({ hasText: contentCode }).first();
  await expect(scriptCard).toBeVisible({ timeout: 20000 });
  await expect(scriptCard).toContainText(formatName);
});
