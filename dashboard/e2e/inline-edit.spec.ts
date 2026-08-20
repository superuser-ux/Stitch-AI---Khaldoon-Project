import { createHmac } from "node:crypto";
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #14 Phase 1 — safe inline edit of the topic title (hook_text). Persisted as a new head revision
// (append-only, audited); structural fields are rejected. Drives the real dashboard (:3000) + API (:8009).
const API = process.env.API_URL || "http://localhost:8009";
const SECRET = process.env.REVIEWER_PROXY_SECRET || "dev-internal-reviewer-proxy-secret";
function adminHeaders() {
  const principal = "khal";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", SECRET).update(principal).digest("hex"),
  };
}
const revs = async (r: APIRequestContext, slot = "RE2E-1") =>
  (await r.get(`${API}/slots/${slot}/revisions?artifact=topic`)).json();

test.beforeEach(() => reseed());

async function openTopicReview(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
}

test("inline title edit updates the active card and preserves version history", async ({ page, request }) => {
  test.setTimeout(120_000);
  const NEW = "عنوان معدّل يدويًا بصمةفريدة";
  await openTopicReview(page);
  expect((await revs(request)).length).toBe(1);

  await page.getByTestId("edit-title-RE2E-1").click();
  const input = page.getByTestId("edit-title-input-RE2E-1");
  await expect(input).toBeVisible();
  await input.fill(NEW);
  await page.getByTestId("edit-title-save-RE2E-1").click();

  // active card immediately shows the edited title
  await expect(page.getByTestId("hero-RE2E-1")).toContainText("بصمةفريدة", { timeout: 15_000 });
  // persisted append-only: v2 marked as a manual edit, v1 preserved
  await expect.poll(async () => (await revs(request)).length).toBe(2);
  const r = await revs(request);
  expect(r[1].change_summary_en).toBe("Manual inline edit");
  expect(r[1].hook_text).toContain("بصمةفريدة");
  expect(r[0].revision).toBe(1);                       // original still there

  // history panel (now available at v2) shows both versions
  await page.getByTestId("history-RE2E-1").click();
  await expect(page.getByTestId("reworkfrom-RE2E-1-1")).toBeVisible();
  await expect(page.getByTestId("reworkfrom-RE2E-1-2")).toBeVisible();
});

test("cancel does not persist and Save is disabled for an empty edit", async ({ page, request }) => {
  await openTopicReview(page);
  const heroBefore = (await page.getByTestId("hero-RE2E-1").innerText()).trim();
  await page.getByTestId("edit-title-RE2E-1").click();
  await page.getByTestId("edit-title-input-RE2E-1").fill("");
  await expect(page.getByTestId("edit-title-save-RE2E-1")).toBeDisabled();   // empty save blocked
  await page.getByTestId("edit-title-input-RE2E-1").fill("مسودة لن تُحفظ");
  await page.getByTestId("edit-title-cancel-RE2E-1").click();
  await expect(page.getByTestId("hero-RE2E-1")).toHaveText(heroBefore);       // unchanged
  expect((await revs(request)).length).toBe(1);                              // nothing persisted
});

test("editing does not disturb counts, and lookup/filter still work", async ({ page }) => {
  await openTopicReview(page);
  const progress = page.getByTestId("disposition-progress");
  await expect(progress).toHaveAttribute("data-total", "3");

  await page.getByTestId("edit-title-RE2E-1").click();
  await page.getByTestId("edit-title-input-RE2E-1").fill("تعديل سريع");
  await page.getByTestId("edit-title-save-RE2E-1").click();
  await expect(page.getByTestId("toast")).toBeVisible();

  // #47 counts stable, #55 filter works, #49 lookup works after an edit
  await expect(progress).toHaveAttribute("data-total", "3");
  await expect(page.locator('[data-testid^="card-RE2E-"]')).toHaveCount(3);
  await page.getByTestId("feed-filter-pending").click();
  await expect(page.locator('[data-testid^="card-RE2E-"]')).toHaveCount(3);
  await page.getByTestId("feed-filter-clear").click();
  await page.getByTestId("content-id-lookup").fill("RE2E-2");
  await page.getByTestId("content-id-lookup-go").click();
  await expect(page.getByTestId("card-RE2E-2")).toHaveAttribute("data-lookup", "match");
});

test("inline topic-body edit updates the card and preserves version history", async ({ page, request }) => {
  test.setTimeout(120_000);
  const NEW = "نص المتن معدّل يدويًا بصمةمتنفريدة";
  await openTopicReview(page);
  await page.getByTestId("density-full").click();   // topic body (text_ar) renders in full density
  await expect(page.getByTestId("topic-body-RE2E-1")).toBeVisible();

  await page.getByTestId("edit-body-RE2E-1").click();
  await page.getByTestId("edit-body-input-RE2E-1").fill(NEW);
  await page.getByTestId("edit-body-save-RE2E-1").click();

  // active card shows the edited body; append-only v2 marked manual; v1 preserved
  await expect(page.getByTestId("topic-body-RE2E-1")).toContainText("بصمةمتنفريدة", { timeout: 15_000 });
  await expect.poll(async () => (await revs(request)).length).toBe(2);
  const r = await revs(request);
  expect(r[1].change_summary_en).toBe("Manual inline edit");
  expect((r[1].body || "")).toContain("بصمةمتنفريدة");
  expect(r[0].revision).toBe(1);

  // the title edit still works alongside the body edit
  await expect(page.getByTestId("edit-title-RE2E-1")).toBeVisible();
});

test("body edit cancel does not persist and Save is disabled when empty", async ({ page, request }) => {
  await openTopicReview(page);
  await page.getByTestId("density-full").click();
  const before = (await page.getByTestId("topic-body-RE2E-1").innerText()).trim();
  await page.getByTestId("edit-body-RE2E-1").click();
  await page.getByTestId("edit-body-input-RE2E-1").fill("");
  await expect(page.getByTestId("edit-body-save-RE2E-1")).toBeDisabled();
  await page.getByTestId("edit-body-input-RE2E-1").fill("مسودة متن لن تُحفظ");
  await page.getByTestId("edit-body-cancel-RE2E-1").click();
  await expect(page.getByTestId("topic-body-RE2E-1")).toHaveText(before);
  expect((await revs(request)).length).toBe(1);
});

test("structural fields are not inline-editable (server rejects them)", async ({ request }) => {
  for (const field of ["hook_type", "pillar_code", "format", "framework"]) {
    const res = await request.post(`${API}/slots/RE2E-1/edit`, {
      headers: adminHeaders(),
      data: { artifact: "topic", field, value: "x" },
    });
    expect(res.status()).toBe(400);
  }
});
