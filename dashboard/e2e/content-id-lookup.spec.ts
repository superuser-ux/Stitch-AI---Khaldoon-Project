import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #49 Phase 2 — the review-surface content-ID lookup consumer. Drives the real dashboard (:3000) on the
// isolated RE2E topic review (3 cards) and asserts an operator can jump to a card by its displayed code
// or internal slot_id, with safe no-match handling and a working clear.
test.beforeEach(() => reseed());

async function openTopicReview(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
}

async function find(page: Page, query: string) {
  await page.getByTestId("content-id-lookup").fill(query);
  await page.getByTestId("content-id-lookup-go").click();
}

test("lookup by displayed content code (expanded) jumps to the matching card", async ({ page }) => {
  await openTopicReview(page);
  const code = (await page.getByTestId("content-id-RE2E-2").innerText()).trim();  // expanded code shown on the card
  await find(page, code);
  await expect(page.getByTestId("lookup-match")).toContainText("RE2E-2");
  await expect(page.getByTestId("card-RE2E-2")).toHaveAttribute("data-lookup", "match");
  await expect(page.getByTestId("card-RE2E-1")).not.toHaveAttribute("data-lookup", "match");
});

test("lookup by internal slot_id jumps to the matching card", async ({ page }) => {
  await openTopicReview(page);
  await find(page, "RE2E-3");
  await expect(page.getByTestId("lookup-match")).toContainText("RE2E-3");
  await expect(page.getByTestId("card-RE2E-3")).toHaveAttribute("data-lookup", "match");
});

test("lookup accepts the compact code and is format-invariant (digits only)", async ({ page }) => {
  await openTopicReview(page);
  await page.getByTestId("idmode-compact").click();
  const compact = (await page.getByTestId("content-id-RE2E-2").innerText()).trim();  // e.g. "01-02-01.01"
  await find(page, compact);
  await expect(page.getByTestId("card-RE2E-2")).toHaveAttribute("data-lookup", "match");
  // same code with all separators stripped still resolves to the same card
  await page.getByTestId("content-id-lookup-clear").click();
  await find(page, compact.replace(/\D/g, ""));
  await expect(page.getByTestId("card-RE2E-2")).toHaveAttribute("data-lookup", "match");
});

test("a missing id shows a safe no-match state and changes nothing", async ({ page }) => {
  await openTopicReview(page);
  await find(page, "99-99-99.99");
  await expect(page.getByTestId("lookup-not-found")).toBeVisible();
  await expect(page.locator('[data-lookup="match"]')).toHaveCount(0);   // nothing highlighted
  await expect(page.locator('[data-testid^="card-RE2E-"]')).toHaveCount(3);   // full surface intact
});

test("clearing the lookup restores the surface", async ({ page }) => {
  await openTopicReview(page);
  await find(page, "RE2E-1");
  await expect(page.getByTestId("card-RE2E-1")).toHaveAttribute("data-lookup", "match");
  await page.getByTestId("content-id-lookup-clear").click();
  await expect(page.locator('[data-lookup="match"]')).toHaveCount(0);
  await expect(page.getByTestId("content-id-lookup")).toHaveValue("");
  await expect(page.locator('[data-testid^="card-RE2E-"]')).toHaveCount(3);
});
