import { expect, test } from "@playwright/test";
import { WB_URL } from "./surfaces";

test("the V2 OpenBao console reports bounded metadata and never renders secret values", async ({ page }) => {
  await page.goto(WB_URL);
  await page.getByTestId("secrets-admin-link").click();
  await expect(page.getByTestId("secrets-admin")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("secret-status-reviewer_proxy")).toBeVisible();
  await expect(page.getByTestId("secret-status-openrouter")).toBeVisible();
  await expect(page.getByTestId("secret-status-groq")).toBeVisible();
  await expect(page.getByTestId("secret-status-scope")).toContainText(
    "does not prove that the external provider currently accepts the credential",
  );
  await expect(page.locator("body")).toContainText("never displays secret values");
  await expect(page.locator("body")).not.toContainText(/sk-or-|gsk_|dev-internal-reviewer-proxy-secret/);
});
