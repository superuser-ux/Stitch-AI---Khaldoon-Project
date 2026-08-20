import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseed } from "./seed";

// Phase-2 coverage: graceful stage states (no scary errors), the explicit human-confirmed
// batch-commit + AI advisory, the integrity guard, the reject path (reversible drop), and the
// live disposition summary. Each test reseeds the isolated RE2E round. Asserts via the API.
const API = process.env.API_URL || "http://localhost:8009";
const round = async (r: APIRequestContext) =>
  (await (await r.get(`${API}/rounds`)).json()).find((x: { round_id: string }) => x.round_id === "RE2E");
const changeStatus = async (r: APIRequestContext, slot: string): Promise<string | undefined> => {
  const ch = await (await r.get(`${API}/rounds/RE2E/changes`)).json();
  return ch.find((c: { slot_id: string }) => c.slot_id === slot)?.status;
};
// #301 — server-declared stage truth (state === next_action): reviewing | ready_to_commit while the
// gate is open, awaiting_regeneration | complete once it has closed.
const topicStage = async (r: APIRequestContext): Promise<{ next_action: string; awaiting: number }> =>
  await (await r.get(`${API}/rounds/RE2E/stages/topic_review/state`)).json();

async function gotoRE2E(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
}
async function startReview(page: Page) {
  await gotoRE2E(page);
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
}

async function center(page: Page, testId: string) {
  await page.getByTestId(testId).evaluate((node) => {
    node.scrollIntoView({ block: "center", inline: "nearest" });
  });
}

async function clickCentered(page: Page, testId: string) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.evaluate((id) => {
      const node = document.querySelector(`[data-testid="${id}"]`);
      (node as HTMLElement | null)?.click();
    }, testId);
    if (!(await page.getByTestId(testId).count())) break;
    await page.waitForTimeout(150);
  }
}

async function checkCentered(page: Page, testId: string) {
  await page.getByTestId(testId).evaluate((node) => {
    (node as HTMLInputElement).click();
  });
}

async function requestChange(page: Page, slot: string, comment: string) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.evaluate((testId) => {
      const node = document.querySelector(`[data-testid="${testId}"]`);
      (node as HTMLElement | null)?.click();
    }, `request-${slot}`);
    if (await page.getByTestId(`change-text-${slot}`).count()) break;
    await page.waitForTimeout(250);
  }
  await expect.poll(async () => await page.getByTestId(`change-text-${slot}`).count()).toBe(1);
  await page.getByTestId(`change-text-${slot}`).fill(comment);
  await page.getByTestId(`submit-change-${slot}`).evaluate((node) => {
    (node as HTMLElement).click();
  });
  await expect(page.getByTestId("toast")).toBeVisible();
}
async function chooseBatchAction(page: Page, label: "Approve selected" | "Request change" | "Drop selected") {
  await page.getByTestId("selected-action").click();
  await page.getByRole("option", { name: label, exact: true }).click();
}
async function applySelected(
  page: Page,
  slots: string[],
  action: "Approve selected" | "Request change" | "Drop selected" = "Approve selected",
  note?: string,
) {
  for (const slot of slots) {
    await checkCentered(page, `select-${slot}`);
  }
  await chooseBatchAction(page, action);
  if (action === "Request change" && note) await page.getByTestId("batch-note").fill(note);
  await page.getByTestId("apply-selected-action").click();
}
// confirm-aware commit: clean batches commit in one click; risky ones (pending / coverage gap) confirm.
async function commit(page: Page) {
  await page.getByTestId("resolve-gate").click();
  const c = page.getByTestId("confirm-commit");
  if (await c.isVisible().catch(() => false)) await c.click();
}

test.beforeEach(() => reseed());

test("per-item actions apply immediately, and dropped items restore cleanly", async ({ page, request }) => {
  await startReview(page);
  await expect(page.getByTestId("awaiting-count-context")).toHaveCount(0);
  const bar = page.getByTestId("disposition-bar");
  await clickCentered(page, "approve-RE2E-1");
  await expect(bar).toContainText("1 approved");
  await expect(bar).toContainText("2 in review");
  await expect(bar).toContainText("2 pending");
  // #24 item 1 — the at-a-glance progress anchor reflects committed resolutions / total
  const progress = page.getByTestId("disposition-progress");
  await expect(progress).toHaveAttribute("data-total", "3");
  await expect(progress).toHaveAttribute("data-resolved", "1");
  await expect(progress).toContainText("1/3");
  // #24 item 2 — the just-approved item is briefly acknowledged (card left the feed but the approval
  // is visibly confirmed) with Restore one click away
  await expect(page.getByTestId("justapproved-panel")).toBeVisible();
  await expect(page.getByTestId("justapproved-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("restore-approved-RE2E-1")).toBeVisible();
  await requestChange(page, "RE2E-2", "غيّر الزاوية");
  await expect(bar).toContainText("1 sent back");
  await clickCentered(page, "reject-RE2E-3");
  // #301 — the immediate reject settles the LAST undecided item, so the review can auto-close as that
  // refresh lands. Both outcomes are governed and legitimate, but the DOM controls are TRANSIENT and
  // cannot discriminate them: resolve-gate stays RENDERED and goes disabled once the tallies reset
  // (nothingDecided), AND it is equally disabled mid-flight (actionBusy) while the refresh is still
  // landing, while confirm-commit unmounts with the bar when the close lands. So no point-in-time
  // count()/isVisible()/isEnabled() sample can tell "still actionable" from "already closed" — the
  // old guard clicked whatever was rendered and blocked on a control that never becomes actionable.
  // (Its /1 dropped|awaiting regeneration/ check was no barrier either: the awaiting panel already
  // renders from the change-request above, so it matched before the reject had even landed.)
  // Branch on the authoritative stage contract instead, which settles on exactly one terminal
  // outcome: ready_to_commit (the gate still needs the governed commit) vs awaiting_regeneration /
  // complete (auto-close already performed the transition). Both terminal states are stable — they
  // hold until a human commits or regenerates — so this is a real barrier, not a timing guess, and
  // the resulting end state is asserted identically below either way.
  await expect.poll(async () => (await topicStage(request)).next_action)
    .toMatch(/^(ready_to_commit|awaiting_regeneration|complete)$/);
  if ((await topicStage(request)).next_action === "ready_to_commit") await commit(page);
  await expect.poll(async () => (await round(request)).topic_approved).toBe(1);
  await expect.poll(async () => await changeStatus(request, "RE2E-2")).toBe("CHANGES_REQUESTED");
  await expect.poll(async () => (await round(request)).rejected).toBe(1);
  await expect(page.getByTestId("dropped-panel")).toBeVisible();
  await expect(page.getByTestId("awaiting-panel")).toBeVisible();
  await expect(page.getByTestId("awaiting-count-context")).toBeVisible();
  // #132 (#131 I4) — the strip must carry the SAME awaiting count as the stage snapshot; number
  // equality against the API, plus one stable copy anchor (full-sentence literals rot — see #115).
  await expect(page.getByTestId("awaiting-count-context")).toContainText("1 awaiting regeneration");
  await expect.poll(async () =>
    (await (await request.get(`${API}/rounds/RE2E/stages/topic_review/state`)).json()).awaiting).toBe(1);
  await expect(page.getByTestId("awaiting-count-context")).toContainText("Counted in the stage total");
  // #24 item 3 — a dropped item exposes a lightweight detail affordance (inspect context before restoring)
  await page.getByTestId("dropped-detail-toggle-RE2E-3").click();
  await expect(page.getByTestId("dropped-detail-RE2E-3")).toBeVisible();
  await expect(page.getByTestId("dropped-detail-RE2E-3")).toContainText("Why dropped");
  // restore (un-reject) -> back in review, nothing lost (history intact: still revision 1)
  await page.getByTestId("restore-RE2E-3").click();
  await expect.poll(async () => (await round(request)).rejected).toBe(0);
  expect((await request.get(`${API}/slots/RE2E-3/revisions?artifact=topic`).then((r) => r.json())).at(-1).revision).toBe(1);
  await gotoRE2E(page);
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();
});

test("batch tools stage selected decisions and support undo before commit", async ({ page }) => {
  await startReview(page);
  const bar = page.getByTestId("disposition-bar");
  await applySelected(page, ["RE2E-1"]);
  await expect(bar).toContainText("1 approved");
  await clickCentered(page, "undo-RE2E-1");
  await expect(bar).toContainText("3 pending");
});

test("actioned cards sink below still-pending cards (issue #3 ordering)", async ({ page }) => {
  await startReview(page);
  // read the review feed's DOM order, restricted to the RE2E review cards
  const feedOrder = () =>
    page.locator('[data-testid^="card-RE2E-"]').evaluateAll((nodes) =>
      nodes
        .map((node) => node.getAttribute("data-testid") || "")
        .filter((id) => /^card-RE2E-\d+$/.test(id)));
  expect(await feedOrder()).toEqual(["card-RE2E-1", "card-RE2E-2", "card-RE2E-3"]);
  // stage an approval on the first card; the actioned card must sink below the still-pending ones
  await applySelected(page, ["RE2E-1"]);
  await expect(page.getByTestId("disposition-bar")).toContainText("1 approved");
  await expect.poll(feedOrder).toEqual(["card-RE2E-2", "card-RE2E-3", "card-RE2E-1"]);
  // undo restores it to its original position — order stays gate-stable within the pending group
  await clickCentered(page, "undo-RE2E-1");
  await expect(page.getByTestId("disposition-bar")).toContainText("3 pending");
  await expect.poll(feedOrder).toEqual(["card-RE2E-1", "card-RE2E-2", "card-RE2E-3"]);
});

test("batch commit advances only the selected approved items", async ({ page, request }) => {
  await startReview(page);
  const bar = page.getByTestId("disposition-bar");
  await applySelected(page, ["RE2E-1", "RE2E-2"]);
  await expect(bar).toContainText("2 approved");
  await expect(bar).toContainText("1 pending");
  await commit(page);
  await expect.poll(async () => (await round(request)).topic_approved).toBe(2);
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();
});

// #47 (BUG-001) regression: the review-surface header metric chips must derive from the SAME
// authoritative snapshot as the visible cards. In the staging window (decisions staged but not
// committed) slot statuses are unchanged, so the round-wide review_pending stays high; the old header
// read review_pending for "Pending" and diverged from the actual pending cards on screen.
test("#47 header metric chips reconcile with the visible cards through the staging window", async ({ page }) => {
  await startReview(page);   // RE2E topic review: 3 pending cards, gate open
  const pending = page.getByTestId("metric-pending");
  const approved = page.getByTestId("metric-approved");
  const progress = page.getByTestId("disposition-progress");
  const cards = page.locator('[data-testid^="card-RE2E-"]');

  // at open: every visible card is pending; nothing decided yet
  await expect(cards).toHaveCount(3);
  await expect(pending).toHaveText("3");
  await expect(approved).toHaveText("0");
  await expect(progress).toHaveAttribute("data-total", "3");
  await expect(progress).toHaveAttribute("data-resolved", "0");

  // stage approvals on TWO items WITHOUT committing — the divergence window. review_pending stays 3
  // (statuses unchanged until commit); the OLD header showed "3 pending" while only ONE card is
  // actually pending. The authoritative chip must reconcile with the single visible pending card.
  await applySelected(page, ["RE2E-1", "RE2E-2"], "Approve selected");
  await expect(page.getByTestId("disposition-bar")).toContainText("2 approved");

  await expect(pending).toHaveText("1");     // the one still-pending visible card (was 3 under old count)
  await expect(approved).toHaveText("2");
  await expect(progress).toHaveAttribute("data-total", "3");
  await expect(progress).toHaveAttribute("data-resolved", "2");   // (was 0 under old count)
  await expect(cards).toHaveCount(3);        // all three cards remain visible (staged, not committed)
});

test("batch tools support selected request-change and drop", async ({ page, request }) => {
  await startReview(page);
  const bar = page.getByTestId("disposition-bar");
  await applySelected(page, ["RE2E-1"], "Request change", "غيّر اللهجة");
  await expect(bar).toContainText("1 sent back");
  await applySelected(page, ["RE2E-2"], "Drop selected");
  await expect(bar).toContainText("1 dropped");
  await commit(page);
  await expect.poll(async () => await changeStatus(request, "RE2E-1")).toBe("CHANGES_REQUESTED");
  await expect.poll(async () => (await round(request)).rejected).toBe(1);
  await expect(page.getByTestId("awaiting-panel")).toBeVisible();
  await expect(page.getByTestId("dropped-panel")).toBeVisible();
});

test("complete state is contextual after a full batch approval", async ({ page }) => {
  await startReview(page);
  await page.getByTestId("select-all-pending").click();
  await chooseBatchAction(page, "Approve selected");
  await page.getByTestId("apply-selected-action").click();
  await expect(page.getByTestId("advisory")).toContainText(/ready to commit/i);   // AI recommends
  await commit(page);
  const bar = page.getByTestId("disposition-bar");
  await expect(bar).toHaveAttribute("data-state", "complete");
  await expect(bar).toContainText(/complete/i);
  await expect(page.locator('[data-testid="toast"][data-kind="err"]')).toHaveCount(0);
  await expect(page.getByTestId("open-gate")).toHaveCount(0);
  // #24 item 5 — a completed stage offers a forward transition to the next stage (topic -> Scripts)
  const advance = page.getByTestId("advance-next-stage");
  await expect(advance).toBeVisible();
  await expect(advance).toContainText("Scripts");
  await advance.click();
  await expect(page.getByTestId("nav-script")).toHaveClass(/font-medium/);
});

test("committing with pending items warns and requires confirmation", async ({ page, request }) => {
  await startReview(page);
  await applySelected(page, ["RE2E-1"]);   // stage 1, leave 2 pending
  await page.getByTestId("resolve-gate").click();     // try to commit early
  await expect(page.getByTestId("advisory")).toContainText(/still pending/i);   // warns
  await expect(page.getByTestId("confirm-commit")).toBeVisible();
  expect((await round(request)).topic_approved).toBe(0);   // NOT committed yet
  await page.getByTestId("confirm-commit").click();
  await expect.poll(async () => (await round(request)).topic_approved).toBe(1);  // committed; pending excluded
  await expect(page.getByTestId("card-RE2E-2")).toBeVisible();   // the excluded items remain in review
  await expect(page.getByTestId("card-RE2E-3")).toBeVisible();
});

test("assistant panel mounts (assistant-ui, no vendor chrome)", async ({ page }) => {
  await gotoRE2E(page);
  await page.getByTestId("assistant-toggle").click();
  await expect(page.getByTestId("assistant-panel")).toBeVisible();
  await expect(page.getByTestId("assistant-input")).toBeVisible();
});

test("disposition summary updates live, per item", async ({ page }) => {
  await startReview(page);
  const bar = page.getByTestId("disposition-bar");
  await expect(bar).toContainText("3 in review");
  await expect(bar).toContainText("3 pending");
  await applySelected(page, ["RE2E-1"]);
  await expect(bar).toContainText("1 approved");
  await expect(bar).toContainText("2 pending");
  await applySelected(page, ["RE2E-2"], "Request change", "غيّر اللهجة");
  await expect(bar).toContainText("1 sent back");
  await applySelected(page, ["RE2E-3"], "Drop selected");
  await expect(bar).toContainText("1 dropped");
  await commit(page);
  await expect(page.getByTestId("toast")).toContainText(/Decisions submitted/i);
});

// #132 — lock the #131 I4 invariant: awaiting > 0 ⇒ the awaiting-regeneration strip renders, and
// its number equals `stage_state.awaiting` (the same snapshot family the cards + disposition bar
// read) — asserted as NUMBER EQUALITY against the API, never as full-sentence copy literals.
test("awaiting strip reconciles with the stage snapshot (#131 I4)", async ({ page, request }) => {
  const stageState = async () =>
    (await request.get(`${API}/rounds/RE2E/stages/topic_review/state`)).json();
  const stripNumber = async () =>
    Number(/⟳\s*(\d+)/.exec((await page.getByTestId("awaiting-count-context").textContent()) || "")?.[1]);
  await startReview(page);
  // awaiting == 0 ⇒ no strip, and the snapshot agrees
  expect((await stageState()).awaiting ?? 0).toBe(0);
  await expect(page.getByTestId("awaiting-count-context")).toHaveCount(0);
  // one send-back ⇒ the strip appears carrying the snapshot's awaiting count
  await requestChange(page, "RE2E-2", "خاطب الشباب");
  await expect(page.getByTestId("awaiting-count-context")).toBeVisible();
  await expect.poll(async () => (await stageState()).awaiting).toBe(1);
  expect(await stripNumber()).toBe(1);
  // the disposition bar reads the same snapshot: its awaiting figure matches the strip
  // (polled — the UI refresh that carries the new stageState may land after the API poll above)
  await expect.poll(async () =>
    Number(/⟳\s*(\d+)/.exec((await page.getByTestId("disposition-bar").textContent()) || "")?.[1])).toBe(1);
  // stable copy anchor only (the strip explains the total-vs-cards reconciliation)
  await expect(page.getByTestId("awaiting-count-context")).toContainText("Counted in the stage total");
  // a second send-back ⇒ the strip tracks the snapshot, not a cached value
  await requestChange(page, "RE2E-3", "زاوية أعمق");
  await expect.poll(async () => (await stageState()).awaiting).toBe(2);
  await expect(page.getByTestId("awaiting-count-context")).toContainText("2 awaiting regeneration");
  await expect.poll(stripNumber).toBe(2);
});
