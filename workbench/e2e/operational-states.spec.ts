import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #315 review finding 3 — the CLOSED deterministic operational-state matrix over the established
// per-item / bulk / reorder surfaces: loading, empty, busy, denied, stale, conflict, partial, error.
// Each state is driven by a CONTROLLED fixture (page.route) — explicitly sanctioned for
// display/error-state rendering (canonical mutation/CAS/byte claims live on the live path, proven
// elsewhere). Every case asserts the typed reason and, where the surface announces it, the accessible
// role. This is deterministic evidence, not observational coverage.

async function anyTopicRun(request: APIRequestContext, min = 1): Promise<{ id: string; slots: string[] }> {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    const inReview = (d.slots || []).filter((s: { status?: string }) => /TOPIC|CHANGE/i.test(s.status || "")) as { slot_id: string }[];
    // Require the caller's MINIMUM up front — a later run may qualify even if an earlier one has too few.
    if (inReview.length >= min) return { id: r.round_id, slots: inReview.map((s) => s.slot_id).sort() };
  }
  throw new Error(`no run with >=${min} Topic item(s) in review — fixture must provision one; a skip would hide defects`);
}

/** A minimal well-formed topic_item read model for DISPLAY-state determinism. */
function itemModel(slot: string, over: Partial<{ editAllowed: boolean; reason: string; headRev: number }> = {}) {
  const editAllowed = over.editAllowed ?? true;
  return {
    slot_id: slot, artifact: "topic", status: "TOPIC_PROPOSED",
    head_revision: over.headRev ?? 1, approved_revision: null,
    identity: { stable_key: "slot_id", slot_id: slot, topic_id_scope: "per_revision" },
    revisions: [{ revision: 1, topic_id: "t0", body: "زاوية عربية", change_summary_ar: null, change_summary_en: null, approved: false }],
    actions: { edit: editAllowed ? { allowed: true } : { allowed: false, reason: over.reason ?? "approved" } },
  };
}

const routeItem = (page: Page, slot: string, over?: Parameters<typeof itemModel>[1]) =>
  page.route(`**/gw/slots/${slot}/topic_item`, (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(itemModel(slot, over)) }));

// ── loading (reorder) ────────────────────────────────────────────────────────────────────────────
test("state: LOADING — the presentation read in-flight shows a real loading state, not a blank/empty", async ({ page, request }) => {
  const { id } = await anyTopicRun(request);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(`**/gw/rounds/${id}/topic-presentation`, async (route) => { await gate; await route.continue(); });
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`, { waitUntil: "commit" });
  await expect(page.getByTestId("wb-tpres-loading")).toBeVisible();   // real in-flight read
  release();
  await expect(page.getByTestId("wb-tpres")).toBeVisible();           // resolves to the real surface
});

// ── empty (bulk) ─────────────────────────────────────────────────────────────────────────────────
test("state: EMPTY — no Topic items in review reads as empty, never as an error", async ({ page, request }) => {
  const { id } = await anyTopicRun(request);
  await page.route((u) => u.pathname === `/gw/rounds/${id}`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ round_id: id, slots: [{ slot_id: `${id}-X`, status: "APPROVED" }] }) }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk-empty")).toBeVisible();
});

// ── busy (bulk) ──────────────────────────────────────────────────────────────────────────────────
test("state: BUSY — an in-flight bulk apply shows a busy affordance and blocks re-submit", async ({ page, request }) => {
  const { id, slots } = await anyTopicRun(request);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(`**/gw/rounds/${id}/bulk-operations`, async (route) => {
    await gate;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ state: "applied", items: [{ slot_id: slots[0], outcome: "succeeded", reason: null }] }) });
  });
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();
  await page.getByTestId(`wb-bulk-select-${slots[0]}`).check();
  await page.getByTestId("wb-bulk-apply").click();
  await expect(page.getByTestId("wb-bulk-apply")).toHaveText(/Applying/);   // busy affordance
  await expect(page.getByTestId("wb-bulk-apply")).toBeDisabled();
  release();
  await expect(page.getByTestId(`wb-bulk-outcome-${slots[0]}`)).toBeVisible();
});

// ── denied (per-item) ────────────────────────────────────────────────────────────────────────────
test("state: DENIED — a server-denied edit is shown disabled WITH the typed machine reason", async ({ page, request }) => {
  const { id, slots } = await anyTopicRun(request);
  const slot = slots[0];
  await routeItem(page, slot, { editAllowed: false, reason: "already_approved" });
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  const denied = page.getByTestId(`wb-topic-item-edit-denied-${slot}`);
  await expect(denied).toBeVisible();
  await expect(denied).toHaveAttribute("data-reason", "already_approved");   // typed reason, not a bare hide
});

// ── stale (per-item edit) ────────────────────────────────────────────────────────────────────────
test("state: STALE — a 409 stale_revision on edit is relayed with the current head + announced", async ({ page, request }) => {
  const { id, slots } = await anyTopicRun(request);
  const slot = slots[0];
  await routeItem(page, slot, { headRev: 1 });
  await page.route(`**/gw/slots/${slot}/edit`, (route) =>
    route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { error: "stale_revision", current: 7 } }) }));
  // the refreshed re-read must still return a model (post-409 load) — keep routeItem in place.
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  // KEYBOARD-only, TYPED-FAILURE path: the stale outcome must both announce AND restore focus.
  await page.getByTestId(`wb-topic-item-edit-${slot}`).focus();
  await page.getByTestId(`wb-topic-item-edit-${slot}`).fill("محاولة تعارض");
  await page.getByTestId(`wb-topic-item-edit-save-${slot}`).focus();
  await page.keyboard.press("Enter");
  const msg = page.getByTestId(`wb-topic-item-write-msg-${slot}`);
  await expect(msg).toBeVisible();
  await expect(msg).toBeFocused();                             // focus restored on the TYPED FAILURE
  await expect(msg).toContainText("rev 7");                    // the current head, relayed
  await expect(msg).toHaveAttribute("role", "status");         // announced
});

// ── conflict (reorder) ───────────────────────────────────────────────────────────────────────────
test("state: CONFLICT — a 409 on reorder surfaces a truthful conflict (never a silent overwrite) + announced", async ({ page, request }) => {
  const { id } = await anyTopicRun(request);
  await page.route(`**/gw/rounds/${id}/topic-presentation-reorder`, (route) =>
    route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ current_token: 42 }) }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-tpres")).toBeVisible();
  // KEYBOARD-only, TYPED-FAILURE path. FIRST rendered row's down control (enabled with >=2 items) —
  // order-independent, since accumulated reorders can move any slot_id to the bottom where its own down
  // control is correctly disabled.
  await page.getByTestId("wb-tpres-list").locator("button[data-testid^='wb-tpres-down-']").first().focus();
  await page.keyboard.press("Enter");
  await page.getByTestId("wb-tpres-apply").focus();
  await page.keyboard.press("Enter");
  const conflict = page.getByTestId("wb-tpres-conflict");
  await expect(conflict).toBeVisible();
  await expect(conflict).toBeFocused();                       // focus restored on the TYPED CONFLICT
  await expect(conflict).toContainText("current 42");
  await expect(conflict).toHaveAttribute("role", "alert");    // announced
});

// ── partial (bulk) ───────────────────────────────────────────────────────────────────────────────
test("state: PARTIAL — a mixed bulk ledger renders each typed per-item outcome verbatim", async ({ page, request }) => {
  // Deterministic discovery — require >=2 in-review slots up front (a later run may qualify); never a
  // conditional skip (a skip is not a pass and would hide a defect).
  const { id, slots } = await anyTopicRun(request, 2);
  const [a, b] = slots;
  await page.route(`**/gw/rounds/${id}/bulk-operations`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      state: "partial",
      items: [{ slot_id: a, outcome: "succeeded", reason: null }, { slot_id: b, outcome: "stale", reason: "stale_revision" }],
    }) }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();
  await page.getByTestId(`wb-bulk-select-${a}`).check();
  await page.getByTestId(`wb-bulk-select-${b}`).check();
  await page.getByTestId("wb-bulk-apply").click();
  await expect(page.getByTestId(`wb-bulk-outcome-${a}`)).toContainText("succeeded");
  await expect(page.getByTestId(`wb-bulk-outcome-${b}`)).toContainText("stale");
  const result = page.getByTestId("wb-bulk-result");
  await expect(result).toContainText("partial");
  await expect(result).toHaveAttribute("role", "status");     // announced
});

// ── typed whole-request error (bulk) — keyboard-only, focus restored ────────────────────────────────
test("state: ERROR (bulk whole-request) — a typed refusal is announced and focus is restored (keyboard-only)", async ({ page, request }) => {
  const { id, slots } = await anyTopicRun(request);
  const slot = slots[0];
  await page.route(`**/gw/rounds/${id}/bulk-operations`, (route) =>
    route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: { error: "unauthorized", detail: "not a topic_review approver" } }) }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();
  await page.getByTestId(`wb-bulk-select-${slot}`).focus();
  await page.keyboard.press("Space");
  await page.getByTestId("wb-bulk-apply").focus();
  await page.keyboard.press("Enter");
  const err = page.getByTestId("wb-bulk-inline-error");
  await expect(err).toBeVisible();
  await expect(err).toBeFocused();                             // focus restored on the TYPED FAILURE
  await expect(err).toContainText("unauthorized");            // the server's typed reason, relayed
  await expect(err).toHaveAttribute("role", "alert");         // announced
});

// ── error (read) — says WHY and offers a retry that RECOVERS ─────────────────────────────────────────
test("state: ERROR — an upstream read failure says WHY and offers a retry that recovers, never a fake empty", async ({ page, request }) => {
  const { id } = await anyTopicRun(request);
  let fail = true;
  await page.route(`**/gw/rounds/${id}/topic-presentation`, async (route) => {
    if (fail) { fail = false; await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "tanaghom api unreachable" }) }); return; }
    await route.continue();     // the retry hits the live path and succeeds
  });
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  const err = page.getByTestId("wb-tpres-error");
  await expect(err).toBeVisible();
  await expect(err).toContainText("tanaghom api unreachable");   // the real upstream reason, not generic
  const retry = page.getByTestId("wb-tpres-retry");
  await expect(retry).toBeVisible();                             // the retry affordance it NAMES
  await retry.click();
  await expect(page.getByTestId("wb-tpres")).toBeVisible();      // retry genuinely recovers
  await expect(page.getByTestId("wb-tpres-error")).toHaveCount(0);
});
