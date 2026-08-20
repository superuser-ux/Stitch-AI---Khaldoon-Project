import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #419 — read-only Stage 4 approval-package preflight surface.
//
// Proves the surface renders the SERVER's typed verdict verbatim for the three governed cases and never
// implies a denied/unavailable path exists. Selectors are the server-driven data-* attributes
// (data-available, data-reason-code, data-denial-code) — the surface reconstructs no eligibility.
//
// These assert against a seeded Stage-4 fixture supplied out of band (canonical slot ids via env), so
// the spec is executed in the runtime validation phase (this implementation dispatch is no-runtime).
// Without the fixture env the cases SKIP rather than false-pass. The coherency/typed-denial logic
// itself is proven runtime-free in gates/stage4_preflight_test.py.

const COHERENT = process.env.STAGE4_COHERENT_SLOT;
const MISMATCH = process.env.STAGE4_MISMATCH_SLOT;
const UNKNOWN = process.env.STAGE4_UNKNOWN_SLOT;
const INVALID_DIRECTION = process.env.STAGE4_INVALID_DIRECTION_SLOT;

async function open(page: import("@playwright/test").Page, slotId: string) {
  await page.goto(`${WB_URL}/stage4/${encodeURIComponent(slotId)}`);
  await expect(page.getByTestId("stage4-preflight")).toHaveAttribute("data-load", "ok");
  return page.getByTestId("stage4-preflight");
}

test.describe("#419 Stage 4 package preflight (read-only)", () => {
  test("coherent package is eligible for human final review", async ({ page }) => {
    test.skip(!COHERENT, "set STAGE4_COHERENT_SLOT to the seeded coherent slot");
    const panel = await open(page, COHERENT!);
    await expect(panel).toHaveAttribute("data-available", "true");
    await expect(panel).toHaveAttribute("data-reason-code", "coherent");
    // Consumed and active workflow identity are both shown; not divergent.
    await expect(page.getByTestId("stage4-divergent")).toHaveText("false");
    await expect(page.getByTestId("stage4-final-review")).toContainText("human-required: true");
    // #419 amendment: production-direction absence before final review is non-blocking; a coherent
    // package is eligible whether the direction is already present or still `not_yet_recorded`.
    const dirStatus = await page.getByTestId("stage4-production-direction").getAttribute("data-direction-status");
    expect(["present", "not_yet_recorded"]).toContain(dirStatus);
    // No denial list and no mutation control on an eligible package.
    await expect(page.getByTestId("stage4-denials")).toHaveCount(0);
    await expect(panel.getByRole("button")).toHaveCount(0);
  });

  test("mismatched topic/script relation fails closed", async ({ page }) => {
    test.skip(!MISMATCH, "set STAGE4_MISMATCH_SLOT to the seeded mismatched slot");
    const panel = await open(page, MISMATCH!);
    await expect(panel).toHaveAttribute("data-available", "false");
    await expect(panel).toHaveAttribute("data-reason-code", "topic_script_mismatch");
    await expect(page.locator('[data-denial-code="topic_script_mismatch"]')).toBeVisible();
    await expect(panel.getByRole("button")).toHaveCount(0);
  });

  test("unknown-history (missing consumed pin) fails closed, never rebinds to active", async ({ page }) => {
    test.skip(!UNKNOWN, "set STAGE4_UNKNOWN_SLOT to the seeded unknown-history slot");
    const panel = await open(page, UNKNOWN!);
    await expect(panel).toHaveAttribute("data-available", "false");
    await expect(page.locator('[data-denial-code="unknown_history"]')).toBeVisible();
    // The consumed identity is reported as unknown — never silently shown as the active generation.
    await expect(page.getByTestId("stage4-consumed-workflow")).toHaveText("unknown");
    await expect(panel.getByRole("button")).toHaveCount(0);
  });

  test("malformed / wrong-script persisted production direction fails closed", async ({ page }) => {
    test.skip(!INVALID_DIRECTION,
      "set STAGE4_INVALID_DIRECTION_SLOT to a seeded slot with a malformed or wrong-script direction");
    const panel = await open(page, INVALID_DIRECTION!);
    // A PERSISTED but malformed/mismatched direction still denies (only ABSENCE is non-blocking) —
    // a non-empty arbitrary payload or a package referencing another script must not pass as present.
    await expect(panel).toHaveAttribute("data-available", "false");
    await expect(page.locator('[data-denial-code^="production_direction_"]')).toBeVisible();
    await expect(panel.getByRole("button")).toHaveCount(0);
  });
});
