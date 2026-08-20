import { createHmac } from "node:crypto";
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseedScriptRound } from "./seed-script";

// #66 — safe inline edit of the script body (script_ar) and the final line (final_line). Persisted as a
// new head revision (append-only, audited); a manual script edit re-opens language + religious sign-off
// (needs_native_review / needs_scholar_review = true). Structural fields are rejected. Drives the real
// dashboard (:3000) + API (:8009) against the isolated RSCR script-review round.
const API = process.env.API_URL || "http://localhost:8009";
const SECRET = process.env.REVIEWER_PROXY_SECRET || "dev-internal-reviewer-proxy-secret";
function adminHeaders() {
  const principal = "khal";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", SECRET).update(principal).digest("hex"),
  };
}
const revs = async (r: APIRequestContext, slot = "RSCR-1") =>
  (await r.get(`${API}/slots/${slot}/revisions?artifact=script`)).json();

test.beforeEach(() => reseedScriptRound());

async function openScriptReview(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RSCR").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-script").click();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("card-RSCR-1")).toBeVisible({ timeout: 20_000 });
}

test("inline script-body edit updates the card, is append-only, and re-opens sign-off", async ({ page, request }) => {
  test.setTimeout(120_000);
  const NEW = "نص السكربت بعد تعديل يدوي بصمةسكربتفريدة";
  // #192 — this test needs a slot whose SEEDED truth is clean (sign-off not yet required) so it
  // can prove the edit FLIPS sign-off open. Since #157, RSCR-1 deliberately seeds
  // needs_native_review: true as the review-state badge fixture (a separate statement from the
  // target context — that contract is asserted in script-stage-surface.spec.ts), so the clean-state
  // subject here is RSCR-3 (managed Hero Reel, seeded clean since #177). Stale-spec fix only:
  // no seeded product truth changed.
  const SLOT = "RSCR-3";
  const before = await revs(request, SLOT);
  expect(before.length).toBe(1);
  expect(before[0].needs_scholar_review).toBe(false);
  expect(before[0].needs_native_review).toBe(false);

  await openScriptReview(page);
  await page.getByTestId(`card-${SLOT}`).getByText("show script", { exact: true }).click();
  await page.getByTestId(`edit-script-${SLOT}`).click();
  await page.getByTestId(`edit-script-input-${SLOT}`).fill(NEW);
  await page.getByTestId(`edit-script-save-${SLOT}`).click();

  // active card shows the edited script body
  await expect(page.getByTestId(`script-body-${SLOT}`)).toContainText("بصمةسكربتفريدة", { timeout: 15_000 });

  // append-only v2 marked manual, sign-off re-opened, v1 preserved untouched
  await expect.poll(async () => (await revs(request, SLOT)).length).toBe(2);
  const r = await revs(request, SLOT);
  expect(r[1].change_summary_en).toBe("Manual inline edit");
  expect((r[1].body || "")).toContain("بصمةسكربتفريدة");
  expect(r[1].needs_scholar_review).toBe(true);
  expect(r[1].needs_native_review).toBe(true);
  expect(r[1].base_revision).toBe(1);
  expect(r[0].revision).toBe(1);
  expect(r[0].needs_scholar_review).toBe(false);   // original revision unchanged
});

test("inline final-line edit updates the locked final line and re-opens sign-off", async ({ page, request }) => {
  test.setTimeout(120_000);
  const NEW = "سطر أخير معدّل يدويًا بصمةنهايةفريدة";
  await openScriptReview(page);
  await page.getByTestId("density-full").click();   // the "Locked final line" block renders in full density
  await expect(page.getByTestId("final-line-RSCR-1")).toBeVisible();

  await page.getByTestId("edit-final-RSCR-1").click();
  await page.getByTestId("edit-final-input-RSCR-1").fill(NEW);
  await page.getByTestId("edit-final-save-RSCR-1").click();

  await expect(page.getByTestId("final-line-RSCR-1")).toContainText("بصمةنهايةفريدة", { timeout: 15_000 });
  await expect.poll(async () => (await revs(request)).length).toBe(2);
  const r = await revs(request);
  expect(r[1].change_summary_en).toBe("Manual inline edit");
  expect((r[1].final_line || "")).toContain("بصمةنهايةفريدة");
  expect(r[1].needs_scholar_review).toBe(true);
  expect(r[1].needs_native_review).toBe(true);
});

test("script edit cancel does not persist and Save is disabled when empty", async ({ page, request }) => {
  await openScriptReview(page);
  await page.getByTestId("card-RSCR-1").getByText("show script", { exact: true }).click();
  const before = (await page.getByTestId("script-body-RSCR-1").innerText()).trim();
  await page.getByTestId("edit-script-RSCR-1").click();
  await page.getByTestId("edit-script-input-RSCR-1").fill("");
  await expect(page.getByTestId("edit-script-save-RSCR-1")).toBeDisabled();
  await page.getByTestId("edit-script-input-RSCR-1").fill("مسودة سكربت لن تُحفظ");
  await page.getByTestId("edit-script-cancel-RSCR-1").click();
  await expect(page.getByTestId("script-body-RSCR-1")).toHaveText(before);
  expect((await revs(request)).length).toBe(1);
});

test("structural / metadata script fields are not inline-editable (server rejects them)", async ({ request }) => {
  for (const field of ["structure", "delivery_notes", "delivery_check", "flags", "model"]) {
    const res = await request.post(`${API}/slots/RSCR-1/edit`, {
      headers: adminHeaders(),
      data: { artifact: "script", field, value: "x" },
    });
    expect(res.status(), `field ${field} must be rejected`).toBe(400);
  }
  // and the whitelisted script fields remain accepted
  const ok = await request.post(`${API}/slots/RSCR-1/edit`, {
    headers: adminHeaders(),
    data: { artifact: "script", field: "script_ar", value: "نص مقبول" },
  });
  expect(ok.status()).toBe(200);
});
