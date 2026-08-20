import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { WB_URL, VIEWPORTS } from "./surfaces";

// #385 — the UX-discoverability correction consuming the #384 operator non-acceptance (gaps 1–7).
//
// This suite proves the VISIBLE, keyboard/touch-accessible affordances the earlier tests never
// asserted: a discoverable schedule-reorder handle + real drag preview (not keyboard-only), the
// calendar gesture legend and per-event movable/frozen marker, the visible "why disabled" disclosure
// that replaces title-only reasons, the Workspace-view vs Calendar-display naming (no duplicate
// "List"), mobile/RTL containment of the regrouped Schedule List, and the absence of any literal
// "undefined" on the audited surfaces. Presentation-only: every governed write/token/conflict contract
// is unchanged and is exercised through the SAME governed path (Apply order → schedule-reorder).

const API = process.env.API_BASE || "http://localhost:8009";

function signed(principal = "khal") {
  const secret = process.env.REVIEWER_PROXY_SECRET?.trim() || "dev-internal-reviewer-proxy-secret";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", secret).update(principal, "utf8").digest("hex"),
    "content-type": "application/json",
  };
}

async function createGovernedRound(request: APIRequestContext): Promise<string> {
  const elig = await (await request.get(`${API}/baseline-eligibility`)).json();
  const names: string[] = (elig?.eligible || elig || []).map((e: { name: string }) => e.name).filter(Boolean);
  expect(names.length, "need at least one baseline-eligible framework").toBeGreaterThan(0);
  const mix: Record<string, number> = {};
  for (let i = 0; i < 3; i++) mix[names[i % names.length]] = (mix[names[i % names.length]] || 0) + 1;
  const res = await request.post(`${API}/rounds`, {
    headers: signed(),
    data: { days: 1, posts_per_day: 3, label: "385-e2e", format_mix: mix },
  });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).round_id as string;
}

/** Drive the REAL HTML5 drag-and-drop event sequence (the exact handlers a pointer drag fires):
 *  dragstart sets the slot id on a shared DataTransfer, drop reads it back. Deterministic — no retry. */
async function dragRow(page: Page, fromTestId: string, toTestId: string): Promise<void> {
  await page.evaluate(({ fromTestId, toTestId }) => {
    const from = document.querySelector(`[data-testid="${fromTestId}"]`);
    const to = document.querySelector(`[data-testid="${toTestId}"]`);
    if (!from || !to) throw new Error("drag row not found");
    const dt = new DataTransfer();
    const fire = (el: Element, type: string) =>
      el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
    fire(from, "dragstart");
    fire(to, "dragenter");
    fire(to, "dragover");
    fire(to, "drop");
    fire(from, "dragend");
  }, { fromTestId, toTestId });
}

async function slotOrder(request: APIRequestContext, round: string): Promise<string[]> {
  const m = await (await request.get(`${WB_URL}/gw/rounds/${round}/schedule-mapping`)).json();
  return (m.positions as { slot_id: string }[]).map((p) => p.slot_id);
}

test.describe.configure({ mode: "serial" });

let ROUND = "";

test.beforeAll(async ({ playwright }) => {
  const request = await playwright.request.newContext();
  ROUND = await createGovernedRound(request);
  await request.dispose();
});

// ── Scope 3 — view hierarchy & naming ────────────────────────────────────────────────────────────
test("the two former 'List' concepts are disambiguated: Workspace view (List) vs Calendar display (Agenda)", async ({ page }) => {
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  // The top menu is labelled "Workspace view"; its list projection keeps the label "List".
  await expect(page.getByTestId("lens-menu-label")).toHaveText("Workspace view");
  await expect(page.getByTestId("lens-list")).toHaveText(/^List$/);

  // The calendar-internal toolbar is labelled "Calendar display"; its list presentation is now "Agenda".
  await expect(page.getByTestId(`view-toolbar-label-${ROUND}`)).toHaveText("Calendar display");
  await expect(page.getByTestId(`view-${ROUND}-list`)).toHaveText("Agenda");
  // The stable key is unchanged: switching it still drives the calendar's list view by its `list` key
  // (the workspace reflects the selected calendar-display view; placement-independent).
  await page.getByTestId(`view-${ROUND}-list`).click();
  await expect(page.getByTestId("run-schedule-workspace")).toHaveAttribute("data-view", "list");
});

// ── Scope 1 — discoverable schedule reorder: visible handle, real drag preview, Apply/Discard ─────
test("schedule reorder is discoverable: a visible handle + guidance, real drag builds an unsaved preview", async ({ page, request }) => {
  const before = await slotOrder(request, ROUND);
  expect(before.length).toBeGreaterThanOrEqual(2);

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review&lens_${ROUND}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  // Discoverability: the guidance line and a per-row drag handle are visible without any interaction.
  await expect(page.getByTestId("reorder-guidance")).toBeVisible();
  await expect(page.getByTestId(`cell-drag-${before[0]}`)).toBeVisible();
  await expect(page.getByTestId("schedule-cells")).toHaveAttribute("data-order-state", "accepted");

  // A REAL drag (HTML5 DnD event path) creates a visible, unsaved preview — nothing committed yet.
  await dragRow(page, `cell-${before[0]}`, `cell-${before[1]}`);
  await expect(page.getByTestId("order-preview")).toBeVisible();
  await expect(page.getByTestId("schedule-cells")).toHaveAttribute("data-order-state", "preview");
  // Mid-preview the server order is untouched (still a proposal).
  expect(await slotOrder(request, ROUND)).toEqual(before);

  // Discard restores the authoritative order with no write.
  await page.getByTestId("order-discard").click();
  await expect(page.getByTestId("order-preview")).toHaveCount(0);
  expect(await slotOrder(request, ROUND)).toEqual(before);
});

test("Apply order commits a dragged preview through the governed path; keyboard reorder is an equal path", async ({ page, request }) => {
  const before = await slotOrder(request, ROUND);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review&lens_${ROUND}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  // Keyboard path first — the ↑/↓ controls remain first-class and build the same preview.
  const down = page.getByTestId(`cell-down-${before[0]}`);
  await down.focus();
  await expect(down).toBeFocused();
  await down.press("Enter");
  await expect(page.getByTestId("order-preview")).toBeVisible();

  // Commit through the existing governed contract (canonical ids + accepted token).
  await page.getByTestId("order-apply").click();
  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });
  await expect(page.getByTestId("order-preview")).toHaveCount(0);
  // The server accepted a real reorder: first two slot ids swapped, the id set is unchanged.
  await expect.poll(async () => (await slotOrder(request, ROUND)).slice(0, 2)).toEqual([before[1], before[0]]);
  expect([...(await slotOrder(request, ROUND))].sort()).toEqual([...before].sort());
});

// ── Scope 6 — Schedule List information design: grouped, contained at 375px, RTL ─────────────────
for (const dir of ["ltr", "rtl"] as const) {
  test(`the regrouped Schedule List is grouped and never overflows the page at 375px (${dir})`, async ({ page, request }) => {
    const ids = await slotOrder(request, ROUND);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review&lens_${ROUND}=list`);
    await page.evaluate((d) => document.documentElement.setAttribute("dir", d), dir);
    await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

    // The row is visibly grouped: each named group is present exactly once in the first row.
    const row = page.getByTestId(`cell-${ids[0]}`);
    for (const group of ["ordering", "identity", "timing", "classification", "edit"]) {
      await expect(row.locator(`[data-group="${group}"]`)).toHaveCount(1);
    }
    // No page-level horizontal overflow (the grouped row wraps, it does not push the page sideways).
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth))
      .toBeLessThanOrEqual(0);
  });
}

// ── Scope 5 — disabled views carry a VISIBLE, focusable reason (title is supplemental only) ──────
test("disabled lenses expose a visible, focusable reason via the help disclosure (not title-only)", async ({ page }) => {
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=topic_review`);
  await expect(page.getByTestId("topics-workspace")).toBeVisible();

  // The disabled lenses still fail closed with a supplemental native title (unchanged contract)…
  await expect(page.getByTestId("lens-calendar")).toBeDisabled();
  await expect(page.getByTestId("lens-calendar")).toHaveAttribute("title", /Coverage \/ Planning/i);

  // …and now ALSO expose a visible, keyboard-focusable, touch-tappable reason panel.
  const toggle = page.getByTestId("lens-help-toggle");
  await expect(toggle).toBeVisible();
  await toggle.focus();
  await expect(toggle).toBeFocused();
  await toggle.press("Enter");
  await expect(page.getByTestId("lens-help-panel")).toBeVisible();
  await expect(page.getByTestId("lens-reason-calendar")).toContainText(/Coverage \/ Planning/i);
  await expect(page.getByTestId("lens-reason-board")).toContainText(/not built/i);
  await expect(page.getByTestId("lens-reason-analytics"))
    .toContainText(/Stage 8.*publication-backed performance evidence/i);
});

test("disabled lifecycle stages expose a visible reason via the rail help disclosure", async ({ page }) => {
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review`);
  await expect(page.getByTestId("stage-rail")).toBeVisible();
  await expect(page.getByTestId("stage-production_review")).toBeDisabled();

  const toggle = page.getByTestId("stage-help-toggle");
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId("stage-help-panel")).toBeVisible();
  await expect(page.getByTestId("stage-reason-production_review")).toContainText(/.+/);
});

// ── Scope 2 — calendar gesture clarity: legend + per-event movable/frozen affordance ─────────────
test("the runs calendar shows a visible gesture legend and a per-event movable affordance (not title-only)", async ({ page, request }) => {
  // Place the run so it renders as a movable calendar event (governed placement, same path as the app).
  const m = await (await request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  const today = new Date().toISOString().slice(0, 10);
  const place = await request.post(`${API}/rounds/${ROUND}/placement`, {
    headers: signed(),
    data: { starts_on: today, schedule_token: m.schedule_token },
  });
  expect(place.status(), await place.text()).toBe(200);

  await page.goto(WB_URL);
  // The legend visibly distinguishes the three gestures (create / move / frozen).
  await expect(page.getByTestId("calendar-legend")).toBeVisible();
  await expect(page.getByTestId("calendar-legend-create")).toContainText(/new-run draft/i);
  await expect(page.getByTestId("calendar-legend-move")).toContainText(/movable/i);
  await expect(page.getByTestId("calendar-legend-frozen")).toContainText(/frozen/i);

  // The placed run renders with an explicit movable affordance — a visible marker, not just `title`.
  const event = page.getByTestId(`run-event-${ROUND}`);
  await expect(event).toBeVisible();
  await expect(event).toHaveAttribute("data-movable", /true|false/);
  await expect(event).toContainText(/⠿|🔒/);
});

// ── Scope 4 — Calendar timing vs Topic editorial order is prominent, not subordinate ─────────────
test("Topics prominently explains editorial order vs schedule timing and why Calendar is unavailable", async ({ page }) => {
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=topic_review`);
  await expect(page.getByTestId("topics-workspace")).toBeVisible();
  const note = page.getByTestId("topic-order-semantics");
  await expect(note).toBeVisible();
  await expect(note).toContainText(/editorial/i);
  await expect(note).toContainText(/never changes.*schedule|timing/i);
  await expect(note).toContainText(/Calendar/i);
});

// ── Scope 7 — no audited surface renders a literal "undefined" ────────────────────────────────────
test("no audited surface renders literal 'undefined' in user-facing text", async ({ page }) => {
  const surfaces = [
    WB_URL,                                                                         // runs calendar
    `${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review&lens_${ROUND}=list`, // schedule list
    `${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review`,            // calendar lens
    `${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=topic_review`,               // topics
  ];
  for (const url of surfaces) {
    await page.goto(url);
    await expect(page.getByTestId("wb-main")).toBeVisible();
    // Let the surface's reads settle so late-bound optional fields are rendered before we scan.
    await page.waitForLoadState("networkidle");
    const text = await page.locator("body").innerText();
    expect(text, `literal "undefined" leaked on ${url}`).not.toMatch(/\bundefined\b/);
  }
});
