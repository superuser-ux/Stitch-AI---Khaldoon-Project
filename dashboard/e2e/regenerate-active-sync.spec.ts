import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #48 (BUG-002) regression: after regeneration the UI must show the regenerated version as the ACTIVE
// content, and any open version-history panel must reflect the new revision — never the pre-regen
// snapshot. Asserted against the real dashboard (:3000) + gate API (:8009, TANAGHOM_WRITER_STUB=1),
// whose stub is comment-responsive (it embeds the reviewer comment into the regenerated topic body).
const API = process.env.API_URL || "http://localhost:8009";
const SLOT = "RE2E-1";

const revs = async (r: APIRequestContext) =>
  (await r.get(`${API}/slots/${SLOT}/revisions?artifact=topic`)).json();

async function openTopicReview(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const openBtn = page.getByTestId("open-gate");
  if (await openBtn.isVisible().catch(() => false)) await openBtn.click();
  await expect(page.getByTestId(`card-${SLOT}`)).toBeVisible();
}

async function requestAndRegen(page: Page, comment: string) {
  await page.getByTestId(`request-${SLOT}`).click();
  await page.getByTestId(`change-text-${SLOT}`).fill(comment);
  await page.getByTestId(`submit-change-${SLOT}`).click();
  await expect(page.getByTestId("toast")).toBeVisible();
  await page.getByTestId("regenerate").click();
}

test.beforeEach(() => reseed());

test("regenerated content becomes the active displayed version", async ({ page, request }) => {
  test.setTimeout(120_000);
  const MARK = "بصمةفحصفريدة";   // unique marker the stub embeds into the regenerated topic body
  await openTopicReview(page);
  await page.getByTestId("density-full").click();   // full density renders the topic body (topic_angle)

  await requestAndRegen(page, MARK);
  await expect.poll(async () => (await revs(request)).length, { timeout: 30_000 }).toBe(2);
  expect(((await revs(request))[1].body || "")).toContain(MARK);

  // the ACTIVE card must render the regenerated content, not the stale v1
  await expect(page.getByTestId(`card-${SLOT}`)).toBeVisible();
  await expect(page.getByTestId(`card-${SLOT}`)).toContainText(MARK, { timeout: 15_000 });
});

test("an open version-history panel reflects a fresh regenerate and keeps prior versions", async ({ page, request }) => {
  test.setTimeout(180_000);
  await openTopicReview(page);

  // cycle 1 -> v2, so the history toggle appears
  await requestAndRegen(page, "خاطب الشباب");
  await expect.poll(async () => (await revs(request)).length, { timeout: 30_000 }).toBe(2);
  await expect(page.getByTestId(`card-${SLOT}`)).toBeVisible();

  // open the history panel while at v2 (shows v1 + v2)
  await page.getByTestId(`history-${SLOT}`).click();
  await expect(page.getByTestId(`versions-${SLOT}`)).toBeVisible();
  await expect(page.getByTestId(`reworkfrom-${SLOT}-1`)).toBeVisible();
  await expect(page.getByTestId(`reworkfrom-${SLOT}-2`)).toBeVisible();
  await expect(page.getByTestId(`reworkfrom-${SLOT}-3`)).toHaveCount(0);

  // cycle 2 -> v3, WITH the history panel open — it must refresh to include v3...
  await requestAndRegen(page, "اربطه بمثال يومي");
  await expect.poll(async () => (await revs(request)).length, { timeout: 30_000 }).toBe(3);
  await expect(page.getByTestId(`card-${SLOT}`)).toBeVisible();
  await expect(page.getByTestId(`versions-${SLOT}`)).toBeVisible();
  await expect(page.getByTestId(`reworkfrom-${SLOT}-3`)).toBeVisible({ timeout: 15_000 });   // fresh
  // ...while KEEPING the prior versions accessible (history is append-only)
  await expect(page.getByTestId(`reworkfrom-${SLOT}-1`)).toBeVisible();
  await expect(page.getByTestId(`reworkfrom-${SLOT}-2`)).toBeVisible();
});
