import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseed } from "./seed";

test.beforeEach(() => reseed());

// End-to-end through the REAL dashboard on the isolated RE2E round, asserting DB/API ground-truth
// after each UI action. Requires: dashboard on :3000, gate API on :8009 with TANAGHOM_WRITER_STUB=1
// (deterministic, comment-responsive regeneration). globalSetup reseeds RE2E + opens its topic gate.
const API = process.env.API_URL || "http://localhost:8009";
const SLOT = "RE2E-1";
const C1 = "خاطب الأب والأم";   // cycle-1 comment (directional)
const C2 = "خاطب الشباب";        // cycle-2 comment (different direction)
const C3 = "اربطه بمثال يومي";   // rework-from comment

type Rev = { revision: number; body: string | null; feedback: string | null; base_revision: number | null; approved: boolean };
const revs = async (r: APIRequestContext): Promise<Rev[]> =>
  (await r.get(`${API}/slots/${SLOT}/revisions?artifact=topic`)).json();
const changeStatus = async (r: APIRequestContext): Promise<string | undefined> => {
  const ch = await (await r.get(`${API}/rounds/RE2E/changes`)).json();
  return ch.find((c: { slot_id: string }) => c.slot_id === SLOT)?.status;
};
const round = async (r: APIRequestContext) =>
  (await (await r.get(`${API}/rounds`)).json()).find((x: { round_id: string }) => x.round_id === "RE2E");

async function gotoRE2E(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
}
async function openReviewGate(page: Page) {     // ensure an open topic gate showing the slot's card
  await gotoRE2E(page);
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const openBtn = page.getByTestId("open-gate");
  if (await openBtn.isVisible().catch(() => false)) await openBtn.click();
  await expect(page.getByTestId(`card-${SLOT}`)).toBeVisible();
}
async function requestChange(page: Page, comment: string) {
  await page.getByTestId(`request-${SLOT}`).click();
  await page.getByTestId(`change-text-${SLOT}`).fill(comment);
  await page.getByTestId(`submit-change-${SLOT}`).click();
  await expect(page.getByTestId("toast")).toBeVisible();
}

test("co-creation + version navigation, asserted against DB/API", async ({ page, request }) => {
  test.setTimeout(240_000);

  await test.step("clean seed: 3 topics, gate open", async () => {
    await openReviewGate(page);
    expect((await round(request)).topic_proposed).toBe(3);
  });

  await test.step("request-change RE2E-1, approve the others, resolve -> CHANGES_REQUESTED", async () => {
    await requestChange(page, C1);
    await expect.poll(async () => await changeStatus(request)).toBe("CHANGES_REQUESTED");
    await page.getByTestId("approve-RE2E-2").click();
    await page.getByTestId("approve-RE2E-3").click();
    await expect.poll(async () => (await round(request)).topic_approved).toBe(2);
  });

  await test.step("CHANGES_REQUESTED is excluded from the queue + shown as awaiting regeneration", async () => {
    await expect(page.getByTestId("awaiting-panel")).toBeVisible();
    await expect(page.getByTestId(`awaiting-${SLOT}`)).toBeVisible();
    await expect(page.getByTestId(`card-${SLOT}`)).toHaveCount(0);   // not re-pulled into review
  });

  await test.step("Regenerate -> v2 that reflects the comment", async () => {
    await page.getByTestId("regenerate").click();
    await expect.poll(async () => (await revs(request)).length, { timeout: 30_000 }).toBe(2);
    const v2 = (await revs(request))[1];
    expect(v2.feedback).toBe(C1);
    expect(v2.body || "").toContain("الأب والأم");                  // comment-responsive
    expect((await round(request)).topic_proposed).toBe(1);          // back in review
    const card = page.getByTestId(`card-${SLOT}`);
    await expect(card).toBeVisible();                               // auto-resumed into actionable review
    await expect(page.getByTestId(`approve-${SLOT}`)).toBeVisible();
    await expect(page.getByTestId(`request-${SLOT}`)).toBeVisible();
    await expect(page.getByTestId(`reject-${SLOT}`)).toBeVisible();
  });

  await test.step("cycle again -> v3 reflects the SECOND comment; history chains linearly", async () => {
    await requestChange(page, C2);
    await expect.poll(async () => await changeStatus(request)).toBe("CHANGES_REQUESTED");
    await gotoRE2E(page);
    await page.getByTestId("nav-topic").click();
    await page.waitForLoadState("networkidle");
    await page.getByTestId("regenerate").click();
    await expect.poll(async () => (await revs(request)).length, { timeout: 30_000 }).toBe(3);
    const r = await revs(request);
    expect(r.map((x) => x.revision)).toEqual([1, 2, 3]);
    expect(r.map((x) => x.feedback)).toEqual([null, C1, C2]);
    expect(r.map((x) => x.base_revision)).toEqual([null, 1, 2]);    // linear chain
    expect(r[2].body || "").toContain("الشباب");
    expect(r[2].body || "").not.toContain("الأب والأم");            // 2nd comment, not the 1st
    await expect(page.getByTestId(`card-${SLOT}`)).toBeVisible();
    await expect(page.getByTestId(`approve-${SLOT}`)).toBeVisible();
    await expect(page.getByTestId(`request-${SLOT}`)).toBeVisible();
    await expect(page.getByTestId(`reject-${SLOT}`)).toBeVisible();
  });

  await test.step("Rework from an EARLIER version (v1) -> linear restore (v4) + rework (v5)", async () => {
    await openReviewGate(page);
    await page.getByTestId(`history-${SLOT}`).click();
    await expect(page.getByTestId(`versions-${SLOT}`)).toBeVisible();
    await page.getByTestId(`reworkfrom-text-${SLOT}-1`).fill(C3);
    // v1 is an OLDER version now (v3 is head) -> reworking from it discards the newer head, so it is
    // gated by an explicit discard confirmation (issue #3 rework-from-older safety).
    await page.getByTestId(`reworkfrom-${SLOT}-1`).click();
    await expect(page.getByTestId(`reworkfrom-warning-${SLOT}-1`)).toBeVisible();
    await page.getByTestId(`reworkfrom-confirm-${SLOT}-1`).click();
    await expect.poll(async () => (await revs(request)).length, { timeout: 30_000 }).toBe(5);
    const r = await revs(request);
    const v4 = r.find((x) => x.revision === 4)!;
    const v5 = r.find((x) => x.revision === 5)!;
    expect(v4.base_revision).toBe(1);                  // restored head copied from v1
    expect(v4.body).toBe(r[0].body);                   // ...content == v1
    expect(v5.base_revision).toBe(4);                  // reworked from the restored head
    expect(r.map((x) => x.revision)).toEqual([1, 2, 3, 4, 5]);  // full history preserved
  });

  await test.step("Approve a NON-latest version (v2 while v5 is head) -> downstream carries v2", async () => {
    await openReviewGate(page);
    await page.getByTestId(`history-${SLOT}`).click();
    await expect(page.getByTestId(`versions-${SLOT}`)).toBeVisible();
    await page.getByTestId(`approve-rev-${SLOT}-2`).click();
    await expect.poll(async () => (await round(request)).topic_approved).toBe(3);
    const r = await revs(request);
    expect(r.filter((x) => x.approved).map((x) => x.revision)).toEqual([2]);   // pinned to v2
    const dirs = await (await request.get(`${API}/slots/${SLOT}/directives`)).json();
    const scriptDir = dirs.filter((d: { to_stage: string }) => d.to_stage === "script").pop();
    expect(scriptDir.revision).toBe(2);                                        // directive carries v2
    expect(scriptDir.payload.context.topic_revision).toBe(2);
  });
});
