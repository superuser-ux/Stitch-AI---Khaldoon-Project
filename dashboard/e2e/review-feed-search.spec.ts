import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { searchFeed, matchesQuery, normalizeQuery } from "../lib/review-search";
import type { Target } from "../lib/review-context";

// #16 / #98 — review-feed text search. Frontend-only: narrows the already-filtered visible feed to
// cards whose already-loaded text/codes match a case-insensitive substring query. No backend/API/schema.

// ── pure logic: normalize + match + narrow, deterministically, without mutating input ──
const mk = (o: Partial<Target>): Target => o as unknown as Target;
// R-1: pillar 01 / seq 02 / day 1 → content code key "01020101"
const A = mk({ slot_id: "R-1", day: 1, time_uae: "09:00", pillar_short_code: "P01", seq_in_pillar: 2, hook_text: "خليك أقوى", topic_angle: "الزاوية الأصلية للذات", pillar_name_en: "Self" });
const B = mk({ slot_id: "R-2", day: 1, time_uae: "09:00", pillar_short_code: "P02", seq_in_pillar: 1, hook_text: "كن حاضرًا", topic_angle: "زاوية العلاقات", pillar_name_en: "Relationships" });
const feed = [A, B];
const ids = (f: Target[]) => f.map((t) => t.slot_id);

test.describe("#98 review search (pure logic)", () => {
  test("normalizeQuery trims, lowercases, and collapses whitespace", () => {
    expect(normalizeQuery("  Foo   Bar ")).toBe("foo bar");
    expect(normalizeQuery("   ")).toBe("");
  });

  test("empty query is a no-op (identity — behaves like no search)", () => {
    expect(searchFeed(feed, "")).toBe(feed);
    expect(searchFeed(feed, "   ")).toBe(feed);
  });

  test("matches by canonical slot_id", () => {
    expect(ids(searchFeed(feed, "R-2"))).toEqual(["R-2"]);
  });

  test("matches by displayed content code", () => {
    expect(ids(searchFeed(feed, "0102"))).toEqual(["R-1"]);   // A's contentIdKey is 01020101
  });

  test("matches by visible copy (Arabic angle + English pillar), case-insensitively", () => {
    expect(ids(searchFeed(feed, "العلاقات"))).toEqual(["R-2"]);   // only B's angle
    expect(ids(searchFeed(feed, "SELF"))).toEqual(["R-1"]);       // pillar_name_en, upshifted query
  });

  test("no match returns empty; input array is never mutated", () => {
    const snapshot = ids(feed);
    expect(searchFeed(feed, "zzznope")).toEqual([]);
    expect(matchesQuery(A, "zzznope")).toBe(false);
    expect(ids(feed)).toEqual(snapshot);
  });
});

// ── browser: the input narrows the live feed, shows a distinct no-match state, and composes ──
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
const cards = (page: Page) => page.locator('[data-testid^="card-RE2E-"]');
async function stageApprove(page: Page, slot: string) {
  await page.getByTestId(`select-${slot}`).evaluate((n) => (n as HTMLInputElement).click());
  await page.getByTestId("selected-action").click();
  await page.getByRole("option", { name: "Approve selected", exact: true }).click();
  await page.getByTestId("apply-selected-action").click();
  await expect(page.getByTestId("disposition-bar")).toContainText("1 approved");
}

test.beforeEach(() => reseed());

test("text search narrows the feed by identifier + visible text, with a distinct no-match state (#98)", async ({ page }) => {
  test.setTimeout(120_000);
  await startReview(page);
  const search = page.getByTestId("feed-search-input");
  await expect(page.getByTestId("feed-search")).toBeVisible();
  await expect(cards(page)).toHaveCount(3);

  // identifier search → the one matching card
  await search.fill("RE2E-2");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-2")).toBeVisible();

  // clearing restores the full feed (empty query == no search)
  await search.fill("");
  await expect(cards(page)).toHaveCount(3);

  // visible-text (Arabic topic angle) search → only the parenting card
  await search.fill("للأبوة");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();

  // no match → distinct search-empty state, no cards, feed not broken
  await search.fill("zzznope-not-a-card");
  await expect(page.getByTestId("feed-search-empty")).toBeVisible();
  await expect(cards(page)).toHaveCount(0);
  await page.getByTestId("feed-search-clear").click();
  await expect(cards(page)).toHaveCount(3);
});

test("search composes with the #55 outcome filter and #96 sort (#98)", async ({ page }) => {
  test.setTimeout(120_000);
  await startReview(page);
  await stageApprove(page, "RE2E-1");                       // RE2E-1 → approved; RE2E-2/3 pending
  await page.getByTestId("feed-sort-select").selectOption("daytime");   // a sort is active

  // outcome filter picks the candidate set (the 2 pending), search narrows within it
  await page.getByTestId("feed-filter-pending").click();
  await expect(cards(page)).toHaveCount(2);
  await page.getByTestId("feed-search-input").fill("RE2E-3");
  await expect(cards(page)).toHaveCount(1);
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();

  // clearing the search returns to the filtered set (filter + sort still applied)
  await page.getByTestId("feed-search-input").fill("");
  await expect(cards(page)).toHaveCount(2);

  // #49 content-ID lookup is a separate control and still present
  await expect(page.getByTestId("content-id-lookup")).toBeVisible();
});
