import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #55 — clickable review-outcome filters on the review surface. Each chip filters the visible feed by the
// item's review outcome; the chip count is the #47 disposition partition, so filtered-visible-count ==
// chip count. Drives the real dashboard (:3000) on the isolated RE2E topic review (3 cards).
test.beforeEach(() => reseed());

const cards = (page: Page) => page.locator('[data-testid^="card-RE2E-"]');

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

async function stageApprove(page: Page, slots: string[]) {
  for (const s of slots) {
    await page.getByTestId(`select-${s}`).evaluate((n) => (n as HTMLInputElement).click());
  }
  await page.getByTestId("selected-action").click();
  await page.getByRole("option", { name: "Approve selected", exact: true }).click();
  await page.getByTestId("apply-selected-action").click();
}

test("clicking Pending filters to pending cards and the count reconciles", async ({ page }) => {
  await openTopicReview(page);
  await expect(cards(page)).toHaveCount(3);
  await expect(page.getByTestId("feed-filter-count-pending")).toHaveText("3");
  await page.getByTestId("feed-filter-pending").click();
  await expect(page.getByTestId("feed-filter-pending")).toHaveAttribute("aria-pressed", "true");
  await expect(cards(page)).toHaveCount(3);          // all pending == the clicked count
  await page.getByTestId("feed-filter-clear").click();
  await expect(cards(page)).toHaveCount(3);
});

test("clicking Approved / Pending filters the feed to exactly the clicked count", async ({ page }) => {
  await openTopicReview(page);
  await stageApprove(page, ["RE2E-1", "RE2E-2"]);
  await expect(page.getByTestId("feed-filter-count-approved")).toHaveText("2");
  await expect(page.getByTestId("feed-filter-count-pending")).toHaveText("1");

  await page.getByTestId("feed-filter-approved").click();
  await expect(cards(page)).toHaveCount(2);          // == Approved count

  await page.getByTestId("feed-filter-pending").click();
  await expect(cards(page)).toHaveCount(1);          // == Pending count

  await page.getByTestId("feed-filter-all").click();
  await expect(cards(page)).toHaveCount(3);          // restored
});

test("an active filter with no matching items shows a safe empty state", async ({ page }) => {
  await openTopicReview(page);
  await stageApprove(page, ["RE2E-1"]);
  await page.getByTestId("feed-filter-approved").click();
  await expect(cards(page)).toHaveCount(1);
  await page.getByTestId("undo-RE2E-1").click();      // the only approved item goes back to pending
  await expect(page.getByTestId("feed-filter-empty")).toBeVisible();
  await page.getByTestId("feed-filter-empty").getByText("Clear filter").click();
  await expect(cards(page)).toHaveCount(3);
});

test("lookup and filter are mutually exclusive and deterministic", async ({ page }) => {
  await openTopicReview(page);
  // a lookup, then a filter -> the filter clears the lookup
  await page.getByTestId("content-id-lookup").fill("RE2E-1");
  await page.getByTestId("content-id-lookup-go").click();
  await expect(page.getByTestId("lookup-match")).toBeVisible();
  await page.getByTestId("feed-filter-pending").click();
  await expect(page.getByTestId("lookup-match")).toHaveCount(0);

  // a filter, then a lookup -> the lookup clears the filter so the match is always visible
  await stageApprove(page, ["RE2E-2"]);
  await page.getByTestId("feed-filter-approved").click();
  await expect(cards(page)).toHaveCount(1);
  await page.getByTestId("content-id-lookup").fill("RE2E-3");
  await page.getByTestId("content-id-lookup-go").click();
  await expect(page.getByTestId("feed-filter-all")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("card-RE2E-3")).toHaveAttribute("data-lookup", "match");
});
