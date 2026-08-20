import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";

// Regression guard for #12 — cross-stage navigation must land on the DESTINATION stage's live state,
// never the previous stage's stale summary; and re-selecting the CURRENT stage must stay a no-op
// (the #3 same-stage guard) so it never blanks the loaded surface.
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

test("cross-stage navigation lands on the fresh destination stage, not the previous stage summary (#12)", async ({ page }) => {
  test.setTimeout(120_000);
  await openTopicReview(page);
  // approve all -> topic stage reaches 'complete'
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("selected-action").click();
  await page.getByRole("option", { name: "Approve selected", exact: true }).click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  const c = page.getByTestId("confirm-commit");
  if (await c.isVisible().catch(() => false)) await c.click();
  const bar = page.getByTestId("disposition-bar");
  await expect(bar).toHaveAttribute("data-state", "complete");
  await expect(bar).toContainText(/complete/i);

  // navigate forward via the #24 item-5 affordance -> the destination (script) must refresh to its
  // OWN live state (generate), never retain the topic 'complete' summary (the #12 defect).
  await page.getByTestId("advance-next-stage").click();
  await expect(bar).toHaveAttribute("data-state", "generate");
  await expect(bar).not.toContainText(/advanced/i);
  await expect(page.getByTestId("nav-script")).toHaveClass(/font-medium/);
});

test("re-selecting the current stage is a no-op and does not blank the surface (#3 guard, #12 boundary)", async ({ page }) => {
  test.setTimeout(90_000);
  await openTopicReview(page);
  // cards are loaded; clicking the stage you are already on must not clear them
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
  await page.getByTestId("nav-topic").click();
  await page.waitForTimeout(600);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("disposition-bar")).toBeVisible();
});
