import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { sortFeed, SORT_OPTIONS, type SortMode } from "../lib/review-sort";
import type { Target } from "../lib/review-context";

// #16 / #96 — review-feed sorting. Frontend-only reorder of the already-filtered visible feed using
// fields already on each Target (day/time/slot_id, content code, staged outcome). No backend/API/schema.

// ── pure logic: sortFeed reorders each mode as specified, deterministically, without mutating input ──
const mk = (o: Partial<Target>): Target => o as unknown as Target;
const outcomeOf = (t: Target) => t.current_outcome;
// incoming order [C, A, B] is unsorted by every key, so each non-default mode must visibly reorder it.
const A = mk({ slot_id: "R-1", day: 1, time_uae: "08:00", pillar_short_code: "P03", seq_in_pillar: 1, current_outcome: "pending" });
const B = mk({ slot_id: "R-2", day: 1, time_uae: "09:00", pillar_short_code: "P01", seq_in_pillar: 2, current_outcome: "approved" });
const C = mk({ slot_id: "R-3", day: 1, time_uae: "15:00", pillar_short_code: "P02", seq_in_pillar: 1, current_outcome: "pending" });
const ids = (feed: Target[]) => feed.map((t) => t.slot_id);

test.describe("#96 sortFeed (pure logic)", () => {
  test("default preserves the incoming order exactly (identity, no re-sort)", () => {
    const feed = [C, A, B];
    const out = sortFeed(feed, "default", outcomeOf);
    expect(ids(out)).toEqual(["R-3", "R-1", "R-2"]);
    expect(out).toBe(feed);   // same reference — existing behavior untouched
  });

  test("daytime sorts by day → time → slot_id, ignoring outcome", () => {
    expect(ids(sortFeed([C, A, B], "daytime", outcomeOf))).toEqual(["R-1", "R-2", "R-3"]);   // 08:00,09:00,15:00
  });

  test("pending-first floats unresolved cards above resolved, day/time within each group", () => {
    // A + C are pending (08:00, 15:00 → R-1, R-3); B is approved → sinks last
    expect(ids(sortFeed([C, A, B], "pending", outcomeOf))).toEqual(["R-1", "R-3", "R-2"]);
  });

  test("code sorts by content code (pillar+struggle+day+post)", () => {
    // keys: R-1=03010101, R-2=01020101, R-3=02010101 → ascending R-2, R-3, R-1
    expect(ids(sortFeed([C, A, B], "code", outcomeOf))).toEqual(["R-2", "R-3", "R-1"]);
  });

  test("every mode is distinct here, deterministic, and non-mutating", () => {
    const feed = [C, A, B];
    const snapshot = ids(feed);
    const results = (["default", "pending", "daytime", "code"] as SortMode[]).map((m) => ids(sortFeed(feed, m, outcomeOf)));
    // all four orders differ → each option really does something
    expect(new Set(results.map((r) => r.join(","))).size).toBe(4);
    // deterministic: same inputs → same output
    for (const m of ["default", "pending", "daytime", "code"] as SortMode[]) {
      expect(ids(sortFeed(feed, m, outcomeOf))).toEqual(ids(sortFeed(feed, m, outcomeOf)));
    }
    expect(ids(feed)).toEqual(snapshot);   // input array never mutated
  });

  test("the four exposed options match the sort modes", () => {
    expect(SORT_OPTIONS.map((o) => o.key)).toEqual(["default", "pending", "daytime", "code"]);
  });
});

// ── browser: the control is wired, reorders the live feed, and composes with the #55 outcome filter ──
async function startReview(page: Page) {
  await page.setViewportSize({ width: 1280, height: 1100 });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });
}
const feedOrder = (page: Page) =>
  page.locator('[data-testid^="card-RE2E-"]').evaluateAll((nodes) =>
    nodes.map((n) => n.getAttribute("data-testid") || "").filter((id) => /^card-RE2E-\d+$/.test(id)));
// stage (not commit) an approval on one card, so its staged outcome flips to "approved"
async function stageApprove(page: Page, slot: string) {
  await page.getByTestId(`select-${slot}`).evaluate((n) => (n as HTMLInputElement).click());
  await page.getByTestId("selected-action").click();
  await page.getByRole("option", { name: "Approve selected", exact: true }).click();
  await page.getByTestId("apply-selected-action").click();
  await expect(page.getByTestId("disposition-bar")).toContainText("1 approved");
}

test.beforeEach(() => reseed());

test("sort control reorders the review feed and Day/time ignores outcome (#96)", async ({ page }) => {
  test.setTimeout(120_000);
  await startReview(page);

  // the control exists with all four options, and default order is unchanged
  await expect(page.getByTestId("feed-sort")).toBeVisible();
  await expect(page.getByTestId("feed-sort-select").locator("option")).toHaveCount(4);
  expect(await feedOrder(page)).toEqual(["card-RE2E-1", "card-RE2E-2", "card-RE2E-3"]);

  // stage an approval on RE2E-1 → under the default pending-first order it sinks to the bottom
  await stageApprove(page, "RE2E-1");
  await expect.poll(() => feedOrder(page)).toEqual(["card-RE2E-2", "card-RE2E-3", "card-RE2E-1"]);

  // Day/time sort ignores outcome → RE2E-1 returns to the top (all same day/time → slot order)
  await page.getByTestId("feed-sort-select").selectOption("daytime");
  await expect.poll(() => feedOrder(page)).toEqual(["card-RE2E-1", "card-RE2E-2", "card-RE2E-3"]);

  // Pending-first sinks the approved card again — a visibly different, deterministic order
  await page.getByTestId("feed-sort-select").selectOption("pending");
  await expect.poll(() => feedOrder(page)).toEqual(["card-RE2E-2", "card-RE2E-3", "card-RE2E-1"]);

  // back to Default: preserved current behavior (orderedTargets pending-first)
  await page.getByTestId("feed-sort-select").selectOption("default");
  await expect.poll(() => feedOrder(page)).toEqual(["card-RE2E-2", "card-RE2E-3", "card-RE2E-1"]);

  // review actions survive sorting — the still-pending cards keep their selection affordance + undo works
  await expect(page.getByTestId("select-RE2E-2")).toBeVisible();
  await expect(page.getByTestId("undo-RE2E-1")).toBeVisible();
});

test("outcome filter (#55) still partitions correctly with a sort active (#96)", async ({ page }) => {
  test.setTimeout(120_000);
  await startReview(page);
  await stageApprove(page, "RE2E-1");
  await page.getByTestId("feed-sort-select").selectOption("daytime");

  // Approved filter → only the approved card, regardless of the active sort
  await page.getByTestId("feed-filter-approved").click();
  await expect(page.locator('[data-testid^="card-RE2E-"]')).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();

  // Pending filter → the two still-pending cards; the approved one is hidden
  await page.getByTestId("feed-filter-pending").click();
  await expect(page.locator('[data-testid^="card-RE2E-"]')).toHaveCount(2);
  await expect(page.getByTestId("card-RE2E-1")).toHaveCount(0);
});
