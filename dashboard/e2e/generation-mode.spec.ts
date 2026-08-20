import { test, expect } from "@playwright/test";
import { reseed } from "./seed";

// #23 — the runtime generation mode must be visible. The e2e/dev stack runs the stub writer
// (TANAGHOM_WRITER_STUB=1), so an unmissable "Generation: Stub" strip must be present, sourced
// from the authoritative /health writer_mode.
test.beforeEach(() => reseed());

test("generation-mode banner surfaces stub mode from /health (#23)", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  const banner = page.getByTestId("gen-mode-banner");
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("data-mode", "stub");
  await expect(banner).toContainText(/Stub/);
  await expect(banner).toContainText(/synthetic/i);
});
