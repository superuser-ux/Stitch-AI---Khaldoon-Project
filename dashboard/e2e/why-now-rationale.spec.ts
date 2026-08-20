import { test, expect } from "@playwright/test";
import { reseed } from "./seed";
import { isMeaningfulRationale } from "../lib/rationale";

// #17 — low-signal / placeholder "Why now" rationale must not clutter the review surface, while a
// genuine reviewer justification stays visible. The stub writer emits placeholders ("concise reason" /
// "سبب مختصر"), so in the e2e/stub stack the section should be suppressed on topic cards.

test.describe("#17 rationale filter (pure logic)", () => {
  test("known placeholders are treated as low-signal; real text is kept", async () => {
    // stub placeholders
    expect(isMeaningfulRationale("concise reason")).toBe(false);
    expect(isMeaningfulRationale("سبب مختصر")).toBe(false);
    // prompt echoes
    expect(isMeaningfulRationale("why this topic now (concise, for the reviewer)")).toBe(false);
    expect(isMeaningfulRationale("ليش هاد الموضوع الآن (مختصر للمراجِع)")).toBe(false);
    // empty / whitespace
    expect(isMeaningfulRationale("")).toBe(false);
    expect(isMeaningfulRationale("   ")).toBe(false);
    expect(isMeaningfulRationale(null)).toBe(false);
    // genuine reviewer justifications are kept
    expect(isMeaningfulRationale("Ramadan engagement peaks this week — timely for the fear angle.")).toBe(true);
    expect(isMeaningfulRationale("مرتبط بموسم الامتحانات وضغط الطلاب هلق")).toBe(true);
  });
});

test.beforeEach(() => reseed());

test("topic full-detail card suppresses the stub placeholder rationale but still renders (#17)", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/"); await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  const card = page.getByTestId("card-RE2E-1");
  await expect(card).toBeVisible();
  // the low-signal 'why-now' section (stub 'concise reason') is not shown as meaningful guidance
  await expect(page.getByTestId("why-now-RE2E-1")).toHaveCount(0);
  await expect(page.getByText("concise reason")).toHaveCount(0);
  // the card itself still renders its actions (suppression did not break the card)
  await expect(page.getByTestId("approve-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("request-RE2E-1")).toBeVisible();
});
