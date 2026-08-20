import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { filterFeed, formatOptions, matchesAttrs, pillarOptions } from "../lib/review-filter";
import type { Target } from "../lib/review-context";

// #16 / #104 — review-feed attribute filters. Frontend-only narrowing by already-loaded pillar +
// content-format fields; no backend/API/schema changes.

const mk = (o: Partial<Target>): Target => o as unknown as Target;
const A = mk({ slot_id: "R-1", pillar_code: "P1_SELF", pillar_name_en: "Self", format: "Hero Reel" });
const B = mk({ slot_id: "R-2", pillar_code: "P2_RELATIONSHIPS", pillar_name_en: "Relationships", format: "Carousel" });
const C = mk({ slot_id: "R-3", pillar_code: "P2_RELATIONSHIPS", pillar_name_en: "Relationships", format: "Hero Reel" });
const feed = [A, B, C];
const ids = (f: Target[]) => f.map((t) => t.slot_id);

test.describe("#104 review attribute filters (pure logic)", () => {
  test("no active attribute filter is a no-op identity", () => {
    expect(filterFeed(feed, { pillar: null, format: null })).toBe(feed);
  });

  test("pillar and format filters each narrow the feed, and compose with AND semantics", () => {
    expect(ids(filterFeed(feed, { pillar: "P2_RELATIONSHIPS", format: null }))).toEqual(["R-2", "R-3"]);
    expect(ids(filterFeed(feed, { pillar: null, format: "Hero Reel" }))).toEqual(["R-1", "R-3"]);
    expect(ids(filterFeed(feed, { pillar: "P2_RELATIONSHIPS", format: "Hero Reel" }))).toEqual(["R-3"]);
    expect(matchesAttrs(B, { pillar: "P2_RELATIONSHIPS", format: "Carousel" })).toBe(true);
    expect(matchesAttrs(B, { pillar: "P1_SELF", format: "Carousel" })).toBe(false);
  });

  test("option helpers expose distinct human-facing choices from already-loaded targets", () => {
    expect(pillarOptions(feed)).toEqual([
      { code: "P2_RELATIONSHIPS", label: "Relationships" },
      { code: "P1_SELF", label: "Self" },
    ]);
    expect(formatOptions(feed)).toEqual(["Carousel", "Hero Reel"]);
  });
});

test.beforeEach(() => reseed());

const cards = (page: Page) => page.locator('[data-testid^="card-RE2E-"]');

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

async function stageApprove(page: Page, slot: string) {
  await page.getByTestId(`select-${slot}`).evaluate((n) => (n as HTMLInputElement).click());
  await page.getByTestId("selected-action").click();
  await page.getByRole("option", { name: "Approve selected", exact: true }).click();
  await page.getByTestId("apply-selected-action").click();
  await expect(page.getByTestId("disposition-bar")).toContainText("1 approved");
}

test("attribute controls render by default and do not narrow the feed until used", async ({ page }) => {
  await startReview(page);
  await expect(page.getByTestId("feed-attr-pillar-select")).toBeVisible();
  await expect(page.getByTestId("feed-attr-format-select")).toBeVisible();
  await expect(cards(page)).toHaveCount(3);
});

test("pillar and content-format filters each narrow the live feed, and can be cleared", async ({ page }) => {
  await startReview(page);

  await page.getByTestId("feed-attr-pillar-select").selectOption("P2_RELATIONSHIPS");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-2")).toBeVisible();

  await page.getByTestId("feed-attr-pillar-select").selectOption("");
  await page.getByTestId("feed-attr-format-select").selectOption("Pic + Caption");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();

  await page.getByTestId("feed-attr-clear").click();
  await expect(cards(page)).toHaveCount(3);
});

test("pillar + format filters compose, and a mismatched combination shows a safe empty state", async ({ page }) => {
  await startReview(page);

  await page.getByTestId("feed-attr-pillar-select").selectOption("P2_RELATIONSHIPS");
  await page.getByTestId("feed-attr-format-select").selectOption("Carousel");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-2")).toBeVisible();

  await page.getByTestId("feed-attr-format-select").selectOption("Hero Reel");
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByTestId("feed-attr-empty")).toBeVisible();
  await page.getByTestId("feed-attr-empty").getByText("Clear attribute filters").click();
  await expect(cards(page)).toHaveCount(3);
});

test("attribute filters compose with outcome filter, search, and an active sort mode", async ({ page }) => {
  await startReview(page);
  await stageApprove(page, "RE2E-1");
  await page.getByTestId("feed-sort-select").selectOption("daytime");
  await page.getByTestId("feed-filter-approved").click();
  await page.getByTestId("feed-attr-pillar-select").selectOption("P1_SELF");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();

  await page.getByTestId("feed-attr-pillar-select").selectOption("");
  await page.getByTestId("feed-filter-all").click();
  await page.getByTestId("feed-attr-format-select").selectOption("Pic + Caption");
  await page.getByTestId("feed-search-input").fill("RE2E-3");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();
  await expect(page.getByTestId("feed-sort-select")).toHaveValue("daytime");
});

test("lookup and attribute filters stay mutually exclusive", async ({ page }) => {
  await startReview(page);

  await page.getByTestId("content-id-lookup").fill("RE2E-1");
  await page.getByTestId("content-id-lookup-go").click();
  await expect(page.getByTestId("lookup-match")).toBeVisible();
  await page.getByTestId("feed-attr-pillar-select").selectOption("P2_RELATIONSHIPS");
  await expect(page.getByTestId("lookup-match")).toHaveCount(0);

  await page.getByTestId("content-id-lookup").fill("RE2E-3");
  await page.getByTestId("content-id-lookup-go").click();
  await expect(page.getByTestId("feed-attr-pillar-select")).toHaveValue("");
  await expect(page.getByTestId("card-RE2E-3")).toHaveAttribute("data-lookup", "match");
});
