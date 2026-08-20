import { test, expect } from "@playwright/test";
import { reseed } from "./seed";

test.beforeEach(() => reseed());

test("overview exposes required approvers and deep-links to the owning approval round", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await page.getByTestId("lens-overview").click();
  await page.waitForLoadState("networkidle");

  const approvals = page.locator("section").filter({ hasText: "My approvals" });
  await expect(approvals).toContainText("RE2E");
  await expect(approvals).toContainText("Matched via: user:Khal");
  await expect(approvals).toContainText("Required approvers: user:Khal");

  await approvals.getByRole("button", { name: /^Open$/ }).first().click();
  await page.waitForLoadState("networkidle");

  // Deep-link landed on the RE2E round. The lunaris redesign moved the round identity out of
  // round-status (now metric chips only) into the topbar round selector, so assert the same fact there.
  await expect(page.getByTestId("round-trigger")).toContainText("RE2E");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  // The redesigned approval-context panel shortened its labels; assert the same three facts (context
  // header, who can act, required approvers) against the current wording.
  await expect(page.getByTestId("my-approval-context")).toContainText("Approval context");
  await expect(page.getByTestId("my-approval-context")).toContainText("Act via");
  await expect(page.getByTestId("my-approval-context")).toContainText("Need");
  await expect(page.getByTestId("my-approval-context")).toContainText("user:Khal");
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
});
