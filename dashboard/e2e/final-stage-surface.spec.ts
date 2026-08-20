import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseedFinalRound } from "./seed-final";

const API = process.env.API_URL || "http://localhost:8009";
const stageState = async (r: APIRequestContext) =>
  (await (await r.get(`${API}/rounds/RFIN/stages/final_review/state`)).json());
const productionState = async (r: APIRequestContext) =>
  (await (await r.get(`${API}/rounds/RFIN/stages/production_review/state`)).json());

async function switchReviewer(page: Page, name: string) {
  const reviewerCombobox = page.getByRole("combobox").nth(1);
  await reviewerCombobox.click();
  await page.getByRole("option", { name: new RegExp(`^${name}$`, "i") }).click();
}

async function gotoRFIN(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RFIN").click();
  await page.waitForLoadState("networkidle");
}

test.beforeEach(() => reseedFinalRound());

test("final stage shows approval code and AND approval context", async ({ page }) => {
  await gotoRFIN(page);
  await page.getByTestId("nav-final").click();

  const card = page.getByTestId("card-RFIN-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/approval code/i);
  await expect(card).toContainText(/framework:/i);
  const approvalContext = page.getByTestId("my-approval-context");
  await expect(approvalContext).toContainText("AND");
  await expect(approvalContext).toContainText(/user:Khal/i);
  await expect(approvalContext).toContainText(/user:Huda/i);
});

test("final stage keeps item pending after only khal approves", async ({ page, request }) => {
  await gotoRFIN(page);
  await page.getByTestId("nav-final").click();

  await page.getByTestId("approve-RFIN-1").click();
  const card = page.getByTestId("card-RFIN-1");
  await expect(card).toContainText(/your decision:/i);
  await expect(card).toContainText(/waiting for the remaining approver/i);
  await expect(card).toContainText(/still required:/i);
  await expect(card).toContainText(/user:Huda/i);
  await expect(page.getByTestId("approve-RFIN-1")).toBeVisible();
  await expect(page.getByTestId("reject-RFIN-1")).toBeVisible();
  await expect(page.getByTestId("undo-RFIN-1")).toBeVisible();
  await expect.poll(async () => (await stageState(request)).state).toBe("reviewing");
  await expect.poll(async () => (await stageState(request)).approved).toBe(0);
});

test("final AND approval advances to production only after the second approver acts", async ({ page, request }) => {
  await gotoRFIN(page);
  await page.getByTestId("nav-final").click();

  await page.getByTestId("approve-RFIN-1").click();
  const finalCard = page.getByTestId("card-RFIN-1");
  await expect(finalCard).toContainText(/your decision:/i);
  await expect(finalCard).toContainText(/waiting for the remaining approver/i);
  await expect.poll(async () => (await stageState(request)).approved).toBe(0);
  await expect.poll(async () => (await productionState(request)).state).toBe("empty");

  await switchReviewer(page, "Huda");
  await expect(page.getByRole("combobox").nth(1)).toContainText(/huda/i);
  await page.getByTestId("approve-RFIN-1").click();

  await expect.poll(async () => (await stageState(request)).state).toBe("reviewing");
  await expect.poll(async () => (await stageState(request)).advanced).toBe(1);
  await expect.poll(async () => (await productionState(request)).state).toBe("ready_to_start");

  await page.getByTestId("nav-production").click();
  const open = page.getByTestId("open-gate");
  await expect(open).toBeVisible({ timeout: 20000 });
  await open.click();
  const productionCard = page.getByTestId("card-RFIN-1");
  await expect(productionCard).toBeVisible({ timeout: 20000 });
  await expect(productionCard).toContainText(/production code/i);
});
