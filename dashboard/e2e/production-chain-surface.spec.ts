import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseedOpsRounds } from "./seed-ops";

const API = process.env.API_URL || "http://localhost:8009";

const stageState = async (r: APIRequestContext, roundId: string, gate: string) =>
  (await (await r.get(`${API}/rounds/${roundId}/stages/${gate}/state`)).json());
const roundState = async (r: APIRequestContext, roundId: string) =>
  (await (await r.get(`${API}/rounds`)).json()).find((x: { round_id: string }) => x.round_id === roundId);

async function gotoRound(page: Page, roundId: string) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId(`round-opt-${roundId}`).click();
  await page.waitForLoadState("networkidle");
}

async function openStageReviewIfNeeded(page: Page) {
  const open = page.getByTestId("open-gate");
  const density = page.getByTestId("density-full");
  await expect.poll(async () => {
    const openVisible = await open.isVisible().catch(() => false);
    const densityVisible = await density.isVisible().catch(() => false);
    return openVisible || densityVisible;
  }, { timeout: 15000 }).toBe(true);
  if (await open.isVisible().catch(() => false)) await open.click();
}

async function openFullCard(page: Page, roundId: string, nav: "production" | "edit" | "distribution") {
  await gotoRound(page, roundId);
  await page.getByTestId(`nav-${nav}`).click();
  await openStageReviewIfNeeded(page);
  await expect(page.getByTestId("density-full")).toBeVisible();
  await page.getByTestId("density-full").click();
}

test.beforeEach(() => reseedOpsRounds());

test("production stage shows directive context, accepts raw-cut media, and resolves one item", async ({ page, request }) => {
  await openFullCard(page, "RPROD", "production");

  const card = page.getByTestId("card-RPROD-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/production code/i);
  await expect(card).toContainText(/directive/i);
  await expect(card).toContainText(/no media yet/i);

  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://raw/RPROD-1-v2");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://raw/RPROD-1-v2");

  await page.getByTestId("approve-RPROD-1").click();
  // #84 — approving a production/edit/distribution item COMMITS and ADVANCES it to the next stage
  // (its status becomes `approve_to`). So stage_state.`approved` (active-gate targets whose outcome is
  // "approved") is a TRANSIENT value the poll can miss once the item advances — the ~15-20% flake.
  // `advanced` = count(slots at `approve_to`) is the DURABLE outcome of a successful approve; assert that.
  await expect.poll(async () => (await stageState(request, "RPROD", "production_review")).advanced).toBe(1);
  await expect(page.getByTestId("card-RPROD-2")).toBeVisible();
});

test("media-edit stage shows incoming directive, accepts edit media, and resolves one item", async ({ page, request }) => {
  await openFullCard(page, "REDIT", "edit");

  const card = page.getByTestId("card-REDIT-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/edit code/i);
  await expect(card).toContainText(/directive/i);
  await expect(card).toContainText(/no media yet/i);

  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://edit/REDIT-1-v2");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://edit/REDIT-1-v2");

  await page.getByTestId("approve-REDIT-1").click();
  await expect.poll(async () => (await stageState(request, "REDIT", "edit_review")).advanced).toBe(1);
  await expect(page.getByTestId("card-REDIT-2")).toBeVisible();
});

test("distribution stage shows final handoff context, accepts post media, and resolves one item", async ({ page, request }) => {
  await openFullCard(page, "RDIST", "distribution");

  const card = page.getByTestId("card-RDIST-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/distribution code/i);
  await expect(card).toContainText(/directive/i);
  await expect(card).toContainText(/no media yet/i);

  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://post/RDIST-1-v1");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://post/RDIST-1-v1");

  await page.getByTestId("approve-RDIST-1").click();
  await expect.poll(async () => (await stageState(request, "RDIST", "distribution_review")).advanced).toBe(1);
  await expect(page.getByTestId("card-RDIST-2")).toBeVisible();
});

test("a production-approved slot can be handed across edit and distribution entirely in the UI", async ({ page, request }) => {
  await openFullCard(page, "RPROD", "production");

  let card = page.getByTestId("card-RPROD-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://raw/RPROD-1-chain");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://raw/RPROD-1-chain");
  await page.getByTestId("approve-RPROD-1").click();
  await expect(page.getByTestId("toast")).toContainText(/applied approval/i);

  await page.getByTestId("nav-edit").click();
  // Landed on the Media edit stage. The redesign renders the stage label as a Scope badge that only
  // appears once the gate has targets (opened below), so assert the stage via the active nav item,
  // which flips as soon as we navigate — a reliable pre-open signal.
  await expect(page.getByTestId("nav-edit")).toHaveClass(/font-medium/);
  {
    const targetCard = page.getByTestId("card-RPROD-1");
    if (!(await targetCard.isVisible().catch(() => false))) {
      const open = page.getByTestId("open-gate");
      await expect(open).toBeVisible({ timeout: 20000 });
      await open.click();
    }
  }
  card = page.getByTestId("card-RPROD-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/edit code/i);
  await page.getByTestId("density-full").click();
  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://edit/RPROD-1-chain");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://edit/RPROD-1-chain");
  await page.getByTestId("approve-RPROD-1").click();
  await expect(page.getByTestId("toast")).toContainText(/applied approval/i);

  await page.getByTestId("nav-distribution").click();
  // Same as the edit stage above: assert the stage landing via the active nav item (the stage-label
  // Scope badge only renders after the gate is opened below).
  await expect(page.getByTestId("nav-distribution")).toHaveClass(/font-medium/);
  {
    const targetCard = page.getByTestId("card-RPROD-1");
    if (!(await targetCard.isVisible().catch(() => false))) {
      const open = page.getByTestId("open-gate");
      await expect(open).toBeVisible({ timeout: 20000 });
      await open.click();
    }
  }
  card = page.getByTestId("card-RPROD-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/distribution code/i);
  await page.getByTestId("density-full").click();
  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://post/RPROD-1-chain");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://post/RPROD-1-chain");
  await page.getByTestId("approve-RPROD-1").click();
  await expect.poll(async () => (await roundState(request, "RPROD")).scheduled).toBe(1);
});
