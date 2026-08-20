import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { isViewValidForStage, coerceViewForStage } from "../lib/views";

// #15 — the working view persists across stage navigation only when valid for the destination stage;
// invalid views (calendar/overview/workflow at a content review stage) fall back to inbox.
test.beforeEach(() => reseed());

test.describe("#15 view-applicability (pure logic)", () => {
  test("card views persist on content stages; non-card views coerce to inbox", async () => {
    // card views valid everywhere
    for (const stage of ["schedule", "topic", "script", "final", "edit", "distribution"]) {
      expect(isViewValidForStage("inbox", stage)).toBe(true);
      expect(isViewValidForStage("grid", stage)).toBe(true);
    }
    // schedule/planning: any view valid (calendar is its board)
    expect(isViewValidForStage("calendar", "schedule")).toBe(true);
    expect(isViewValidForStage("overview", "schedule")).toBe(true);
    // content review stages: non-card views are invalid
    expect(isViewValidForStage("calendar", "topic")).toBe(false);
    expect(isViewValidForStage("overview", "script")).toBe(false);
    expect(isViewValidForStage("workflow", "final")).toBe(false);
    // coercion
    expect(coerceViewForStage("grid", "script")).toBe("grid");     // kept
    expect(coerceViewForStage("calendar", "topic")).toBe("inbox"); // fallback
    expect(coerceViewForStage("calendar", "schedule")).toBe("calendar");
  });
});

async function openRE2E(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
}
const main = (page: Page) => page.getByTestId("review-main");

test("a valid card view persists across a content-stage switch (#15)", async ({ page }) => {
  await openRE2E(page);
  await page.getByTestId("nav-topic").click();
  await page.getByTestId("lens-grid").click();
  await expect(main(page)).toHaveAttribute("data-view", "grid");
  await page.getByTestId("nav-script").click();
  await page.waitForTimeout(600);
  await expect(main(page)).toHaveAttribute("data-view", "grid");        // kept (grid is a card view)
  await expect(page.getByTestId("nav-script")).toHaveClass(/font-medium/);
});

test("an invalid view (calendar) falls back to inbox when entering a content stage (#15)", async ({ page }) => {
  await openRE2E(page);
  await page.getByTestId("lens-calendar").click();
  await expect(main(page)).toHaveAttribute("data-view", "calendar");
  await page.getByTestId("nav-topic").click();
  await page.waitForTimeout(600);
  await expect(main(page)).toHaveAttribute("data-view", "inbox");       // coerced (calendar hides cards)
});

test("reload coerces a stale saved calendar view to inbox at a content stage (#15)", async ({ page }) => {
  await openRE2E(page);
  // force a saved 'calendar' view while parked on the topic stage, then reload
  await page.getByTestId("nav-topic").click();
  await page.evaluate(() => { window.localStorage.setItem("tanaghom-view", "calendar"); window.localStorage.setItem("tanaghom-stage", "topic"); });
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(main(page)).toHaveAttribute("data-view", "inbox");       // restore respected applicability
});

test("a lens drill-down opens the review surface / inbox (#15)", async ({ page }) => {
  await openRE2E(page);
  await page.getByTestId("lens-overview").click();
  await expect(main(page)).toHaveAttribute("data-view", "overview");
  await page.getByRole("button", { name: /^Open/ }).first().click();
  await expect(main(page)).toHaveAttribute("data-view", "inbox");
});
