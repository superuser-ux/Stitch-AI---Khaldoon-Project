import { test, expect, type Page } from "@playwright/test";
import { allocateFullMix } from "./plan-helpers";

async function openReviewIfNeeded(page: Page) {
  const card = page.locator("[data-testid^=card-]").first();
  if (await card.isVisible().catch(() => false)) return;
  const open = page.getByTestId("open-gate");
  await expect(open).toBeVisible({ timeout: 20000 });
  await open.click();
}

test("browser content handoff flows from schedule through final approval", async ({ page }) => {
  test.setTimeout(240_000);

  await page.goto("/");

  await page.getByTestId("new-run").click();
  await page.getByTestId("label-input").fill("content-handoff-e2e");
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill("1");
  await expect(page.getByTestId("run-total")).toHaveText("1");
  await allocateFullMix(page);
  await page.getByTestId("new-run-submit").click();
  await expect(page.getByTestId("round-trigger")).toContainText("content-handoff-e2e");
  await expect(page.getByTestId("round-trigger")).toContainText(/R\d+/);
  // Schedule
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("open-gate").click();
  await expect(page.getByTestId("select-all-pending")).toBeVisible({ timeout: 20000 });
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await expect(page.getByTestId("toast")).toContainText(/decisions submitted/i);

  // Topics
  await page.getByTestId("nav-topic").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  await expect(page.getByTestId("job-progress")).toBeVisible();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await page.getByTestId("open-gate").click();
  let card = page.locator("[data-testid^=card-]").first();
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/topic code/i);
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();

  // Scripts
  await page.getByTestId("nav-script").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  await expect(page.getByTestId("job-progress")).toBeVisible();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await page.getByTestId("open-gate").click();
  card = page.locator("[data-testid^=card-]").first();
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/script code/i);
  await card.getByRole("button", { name: /show script/i }).click();
  await expect(card).toContainText(/hide script/i);
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();

  // Final approval handoff
  await page.getByTestId("nav-final").click();
  await openReviewIfNeeded(page);
  card = page.locator("[data-testid^=card-]").first();
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/approval code/i);
  // The acting reviewer (Khal) is a required approver at the final stage, so the approval rule shows in
  // the "my approval context" panel; a non-assignee would see it in "gate-assignments". Assert whichever
  // renders (the choice depends on when pending-approvals finish loading) so this isn't a race.
  await expect(page.getByTestId("gate-assignments").or(page.getByTestId("my-approval-context"))).toContainText(/and|or/i);
});
