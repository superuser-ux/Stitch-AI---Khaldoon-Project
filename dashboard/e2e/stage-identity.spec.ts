import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { canonicalGate, stageLabel, stageIdentity, stageDebugId } from "../lib/stages";

// #39 slice 1 — canonical stage identity vs operator-facing label.
test.describe("#39 stage identity (pure logic)", () => {
  test("alias resolves to canonical gate id; identity is stable", async () => {
    // dashboard alias -> canonical persisted gate id (NEVER renamed)
    expect(canonicalGate("final")).toBe("final_review");
    expect(canonicalGate("topic")).toBe("topic_review");
    expect(canonicalGate("distribution")).toBe("distribution_review");
    // resolving by the canonical id is idempotent (no rename implied)
    expect(canonicalGate("final_review")).toBe("final_review");
    // debug identity is the canonical gate + alias, never the mutable label
    expect(stageDebugId("final")).toBe("final_review(final)");
  });

  test("preferred label for the pre-production sign-off stage is 'Pre Production Approval'", async () => {
    expect(stageLabel("final")).toBe("Pre Production Approval");
    expect(stageLabel("final_review")).toBe("Pre Production Approval");
    expect(stageIdentity("final")?.meaning).toMatch(/pre-production sign-off/i);
    // the misleading old label is gone
    expect(stageLabel("final")).not.toBe("Publish approval");
    // other labels are unchanged
    expect(stageLabel("topic")).toBe("Topics");
    expect(stageLabel("script")).toBe("Scripts");
  });

  test("canonical gate ids match the persisted engine set (no rename)", async () => {
    for (const [alias, gate] of [
      ["schedule", "schedule_review"], ["topic", "topic_review"], ["script", "script_review"],
      ["final", "final_review"], ["production", "production_review"], ["edit", "edit_review"],
      ["distribution", "distribution_review"],
    ] as const) {
      expect(canonicalGate(alias)).toBe(gate);
    }
  });
});

test.beforeEach(() => reseed());

test("the review nav shows the preferred pre-production label, not 'Publish approval' (#39)", async ({ page }: { page: Page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("nav-final")).toHaveAttribute("title", "Pre Production Approval");
  await expect(page.getByText("Publish approval")).toHaveCount(0);
});
