import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { WB_URL } from "./surfaces";

// #372 — browser operator-journey acceptance: Schedule → Topic → Script.
//
// BINDING RULINGS (Codex reconciliation on #372, implemented here):
//  PRE-01  STAGE ADVANCEMENT is GOVERNED SETUP, never a claimed browser control. V2 exposes no
//          resolve/commit/advance write path. Every transition below is performed through canonical
//          API routes and is explicitly labelled `governedSetup*`; no test claims a browser-driven
//          stage advancement.
//  PRE-02  RECOVERY = `reopen`. `restore_revision` has NO control by design and is never asserted as
//          passed functionality (SCR-03 asserts the alias is absent).
//  PRE-03  V2's Drop/approve/request_change are RECORD-ONLY. TOP-05 asserts that truth explicitly —
//          a decision is recorded AND the item does NOT transition. Nothing here implies V2 committed.
//
// Every IN-STAGE action is driven through a VISIBLE RENDERED CONTROL and correlated with an
// INDEPENDENT persistence read after reload. Test titles are prefixed with their matrix row id so the
// evidence bundle can join matrix ID → result/artifact.

const API = process.env.API_BASE || "http://127.0.0.1:8370";

function signed(principal = "khal") {
  const secret = process.env.REVIEWER_PROXY_SECRET?.trim() || "dev-internal-reviewer-proxy-secret";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", secret).update(principal, "utf8").digest("hex"),
    "content-type": "application/json",
  };
}

/** GOVERNED SETUP (PRE-01) — advance a stage through canonical API routes. NEVER a browser claim. */
async function governedSetupAdvance(req: APIRequestContext, rid: string, stage: string) {
  const g = await (await req.post(`${API}/gates`, { headers: signed(), data: { stage, round_id: rid } })).json();
  const gid = g.gate_id || g.gate?.gate_id;
  await req.post(`${API}/gates/${gid}/decide`, { headers: signed(), data: { decision: "approve" } });
  await req.post(`${API}/gates/${gid}/resolve`, { headers: signed(), data: {} });
}

async function frameworkName(req: APIRequestContext): Promise<string> {
  await req.get(`${API}/workflow-versions/active`);            // seed the baseline governed version
  const elig = await (await req.get(`${API}/baseline-eligibility`)).json();
  const names: string[] = (elig.eligible || elig.frameworks || []).map((f: { name: string }) => f.name);
  expect(names.length, "candidate lane must have baseline-eligible frameworks").toBeGreaterThan(0);
  return names[0];
}

/** GOVERNED SETUP (#376) — mint a CURRENT run-mix recommendation-policy generation through the
 *  authority's own authorized administration path. The browser composer cannot plan a run without a
 *  governed recommendation (by design: no client-invented mix), so this is fixture setup, exactly like
 *  `governedSetupAdvance`. Minting is idempotent for a disposable lane: #377 supersedes the previous
 *  generation rather than editing it. */
async function governedSetupRunMixPolicy(req: APIRequestContext) {
  const cur = await (await req.get(`${API}/run-mix-policy`)).json();
  if (cur.status === "current") return;
  const elig = await (await req.get(`${API}/baseline-eligibility`)).json();
  const eligible = (elig.eligible || elig.frameworks || []) as { name: string; version_id: string }[];
  const weights: Record<string, number> = {};
  for (const f of eligible) weights[f.version_id] = 1;
  const res = await req.post(`${API}/run-mix-policy`, { headers: signed(), data: { weights, notes: "#372 lane" } });
  expect(res.status(), await res.text()).toBe(200);
}

/** A fresh schedule-open (revisable) run — governed setup only up to run creation. */
async function scheduleOpenRun(req: APIRequestContext, label: string): Promise<string> {
  const fw = await frameworkName(req);
  const mk = await req.post(`${API}/rounds`, { headers: signed(),
    data: { days: 1, posts_per_day: 3, label, format_mix: { [fw]: 3 } } });
  expect(mk.status(), await mk.text()).toBe(200);
  return (await mk.json()).round_id as string;
}

/** A run at topic_review with an EDITABLE generated topic (schedule advancement = GOVERNED SETUP). */
async function topicReviewSlot(req: APIRequestContext, label: string): Promise<{ rid: string; slot: string }> {
  const rid = await scheduleOpenRun(req, label);
  await governedSetupAdvance(req, rid, "schedule_review");     // PRE-01 governed setup
  for (let i = 0; i < 40; i++) {
    const res = await req.get(`${API}/rounds/${rid}/generation`);
    if (res.ok()) {
      const m = await res.json();
      for (const r of (m.results || []) as { topic: unknown; slot_id: string }[]) {
        if (!r.topic) continue;
        const item = await req.get(`${API}/slots/${r.slot_id}/topic_item`);
        if (item.ok() && (await item.json())?.actions?.edit?.allowed === true) return { rid, slot: r.slot_id };
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("fixture: no editable generated topic appeared");
}

/** A run at script_review with a DRAFT_ASSIGNED script (both advancements = GOVERNED SETUP). */
async function scriptReviewSlot(req: APIRequestContext, label: string): Promise<{ rid: string; slot: string }> {
  const { rid } = await topicReviewSlot(req, label);
  await governedSetupAdvance(req, rid, "topic_review");        // PRE-01 governed setup
  for (let i = 0; i < 40; i++) {
    const r = await req.get(`${API}/rounds/${rid}`);
    if (r.ok()) {
      const slot = ((await r.json()).slots || []).find((s: { status: string }) => s.status === "DRAFT_ASSIGNED");
      if (slot) return { rid, slot: slot.slot_id };
    }
    await new Promise((x) => setTimeout(x, 500));
  }
  throw new Error("fixture: no DRAFT_ASSIGNED script appeared");
}

/** GOVERNED SETUP — give the run an absolute placement so the CALENDAR surface renders (an unplaced
 *  run renders `run-schedule-calendar-unplaced` instead). Placement is a governed route, used here as
 *  setup so the row can exercise calendar NAVIGATION through visible controls. */
async function governedSetupPlace(req: APIRequestContext, rid: string) {
  const m = await (await req.get(`${API}/rounds/${rid}/schedule-mapping`)).json();
  const r = await req.post(`${API}/rounds/${rid}/placement`, { headers: signed(),
    data: { starts_on: "2026-09-01", schedule_token: m.schedule_token } });
  expect(r.status(), await r.text()).toBe(200);
}

/** GOVERNED SETUP (PRE-01) — COMMIT a drop decision for one slot so `reopen` becomes eligible.
 *  The commit floor is never a browser control; it is performed here through canonical API routes. */
async function governedSetupCommitDrop(req: APIRequestContext, rid: string, slot: string, stage: string) {
  const g = await (await req.post(`${API}/gates`, { headers: signed(), data: { stage, round_id: rid } })).json();
  const gid = g.gate_id || g.gate?.gate_id;
  await req.post(`${API}/gates/${gid}/decide`, { headers: signed(), data: { decision: "reject", slot_ids: [slot] } });
  await req.post(`${API}/gates/${gid}/resolve`, { headers: signed(), data: {} });
}

/** A browser-issued /gw read (same-origin) — INDEPENDENT persistence evidence. */
async function gwRead(page: Page, path: string) {
  return await page.evaluate(async (p) => {
    const r = await fetch(p);
    let b: unknown = {}; try { b = await r.json(); } catch { /* */ }
    return { s: r.status, b: b as Record<string, unknown> };
  }, path);
}

test.describe.configure({ mode: "serial" });

// ---------------------------------------------------------------- Schedule
// #376 — the detached Create-run form is superseded by the ONE ephemeral composer. The ROW's meaning
// is unchanged (create a run through visible controls, with independent persistence evidence); only the
// controls it drives moved, because the surface it named no longer exists.
test("SCH-01 create a run through the visible run composer", async ({ request, page }) => {
  await frameworkName(request);                    // seeds the baseline governed version
  await governedSetupRunMixPolicy(request);        // #376 governed setup: the composer needs an authority
  await page.goto(`${WB_URL}/`);
  await page.getByTestId("new-run").click();
  await expect(page.getByTestId("run-composer")).toBeVisible();
  await page.getByTestId("composer-posts").fill("2");
  await page.getByTestId("composer-label").fill("372-sch01");
  await page.getByTestId("composer-recommend").click();
  await expect(page.getByTestId("composer-mix-inputs"), "the governed mix renders").toBeVisible({ timeout: 30_000 });
  await page.getByTestId("composer-submit").click();
  // visible outcome: we land on the new run's schedule stage
  await page.waitForURL(/\/runs\/.+/, { timeout: 60_000 });
  const rid = (page.url().match(/\/runs\/([^?]+)/) || [])[1];
  expect(rid, "a run id is in the URL after Plan run").toBeTruthy();
  // independent persistence after reload
  await page.reload();
  const r = await gwRead(page, `/gw/rounds/${rid}`);
  expect(r.s).toBe(200);
  expect(((r.b.slots || []) as unknown[]).length, "the created run has slots").toBeGreaterThan(0);
});

test("SCH-01N invalid mix is refused non-mutatively by the server's typed refusal", async ({ request, page }) => {
  await governedSetupRunMixPolicy(request);
  await page.goto(`${WB_URL}/`);
  await page.getByTestId("new-run").click();
  await page.getByTestId("composer-posts").fill("3");
  await page.getByTestId("composer-recommend").click();
  await expect(page.getByTestId("composer-mix-inputs")).toBeVisible({ timeout: 30_000 });
  // AMEND the governed mix into an invalid one: drop a slot so the total no longer fills the run. The
  // recommendation was valid; the operator's amendment is not, and the SERVER says so.
  const box = page.locator('[data-testid^="composer-mix-"][data-recommended]').first();
  const rec = Number(await box.getAttribute("data-recommended"));
  await box.fill(String(Math.max(0, rec - 1)));
  await expect(page.getByTestId("composer-mix-total"), "the mix total is surfaced").toBeVisible();
  // The surface does NOT gate submit client-side: the planner owns the mix contract, so the refusal is
  // the SERVER's typed 422 relayed verbatim. Assert the real behaviour — a typed, NON-MUTATING refusal
  // that neither navigates nor creates a run (V2 invents no client-side validation).
  // INDEPENDENT non-mutation evidence: capture the run set BEFORE, then prove it is unchanged after.
  const before = await gwRead(page, "/gw/rounds");
  const beforeIds = ((before.b as unknown as { round_id: string }[]) || []).map((r) => r.round_id).sort();
  await page.getByTestId("composer-label").fill("372-sch01n-must-not-exist");
  await page.getByTestId("composer-submit").click();
  await expect(page.getByTestId("composer-feedback"), "the server's typed refusal is relayed verbatim").toBeVisible({ timeout: 30_000 });
  await expect(page, "an invalid mix must NOT navigate to a created run").toHaveURL(/\/$|\/\?/);
  const after = await gwRead(page, "/gw/rounds");
  const afterRows = ((after.b as unknown as { round_id: string; label?: string }[]) || []);
  expect(afterRows.map((r) => r.round_id).sort(), "NON-MUTATING: the run set is unchanged").toEqual(beforeIds);
  expect(afterRows.filter((r) => (r.label || "").includes("372-sch01n-must-not-exist")).length,
    "no run was created by the refused submission").toBe(0);
});

test("SCH-02 inspect and navigate the run's scheduled slots", async ({ request, page }) => {
  const rid = await scheduleOpenRun(request, "372-sch02");
  await governedSetupPlace(request, rid);            // an UNPLACED run renders no calendar to navigate
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review&lens_${rid}=list`);
  await expect(page.getByTestId("schedule-cells"), "the slot list renders").toBeVisible({ timeout: 90_000 });
  await expect(page.locator('[data-testid^="cell-down-"]').first(), "per-slot controls render").toBeVisible();
  // Journey 2 requires NAVIGATING the schedule: actually switch the calendar view through the visible
  // toolbar and assert the rendered view CHANGED (data-view is the calendar's own rendered state).
  // #376 — the calendar is one of three lenses over the SAME slots, so it is selected through its own
  // visible control first. Both lenses are exercised in this row, which is stronger than before.
  await page.getByTestId("lens-calendar").click();   // #382 — lens selector now in the shell top menu
  const cal = page.getByTestId("run-schedule-calendar");
  await expect(cal, "the calendar renders").toBeVisible();
  const before = await cal.getAttribute("data-view");
  const target = before === "month" ? "list" : "month";
  await page.locator(`[data-testid$="-${target}"]`).first().click();
  await expect(cal, `the toolbar switched the rendered calendar view to ${target}`).toHaveAttribute("data-view", target, { timeout: 30_000 });
  await page.reload();
  await page.getByTestId("lens-list").click();   // #382 — lens selector now in the shell top menu
  await expect(page.getByTestId("schedule-cells"), "slots persist after reload").toBeVisible({ timeout: 90_000 });
});

test("SCH-03 governed schedule reorder through the visible move + Apply controls", async ({ request, page }) => {
  const rid = await scheduleOpenRun(request, "372-sch03");
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review&lens_${rid}=list`);
  const before = await gwRead(page, `/gw/rounds/${rid}/schedule-mapping`);
  const token0 = before.b.schedule_token as number;
  const codes0 = ((before.b.positions || []) as { display_code: string }[]).map((p) => p.display_code).join(",");
  await page.locator('[data-testid^="cell-down-"]').first().click();
  await page.getByTestId("order-apply").click();
  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 30_000 });
  // independent persistence after reload
  await page.reload();
  const after = await gwRead(page, `/gw/rounds/${rid}/schedule-mapping`);
  expect((after.b.schedule_token as number) > token0, "the governed reorder advanced the schedule token").toBeTruthy();
  expect(((after.b.positions || []) as { display_code: string }[]).map((p) => p.display_code).join(","),
    "the accepted order changed and persisted").not.toBe(codes0);
});

// ---------------------------------------------------------------- Topic
test("TOP-01 per-item panel + immutable revision history render", async ({ request, page }) => {
  const { rid, slot } = await topicReviewSlot(request, "372-top01");
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId(`wb-topic-item-head-${slot}`), "head revision is disclosed").toBeVisible();
  await expect(page.getByTestId(`wb-topic-item-history-${slot}`).locator(":scope > li").first(),
    "the append-only history renders at least one revision").toBeVisible();
});

test("TOP-02 governed edit appends a durable new revision", async ({ request, page }) => {
  const { rid, slot } = await topicReviewSlot(request, "372-top02");
  const head0 = ((await gwRead(await pageAt(page, `${WB_URL}/`), `/gw/slots/${slot}/topic_item`)).b.head_revision) as number;
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  await page.getByTestId(`wb-topic-item-edit-${slot}`).fill("نص محرَّر عبر رحلة المشغّل #372");
  await page.getByTestId(`wb-topic-item-edit-save-${slot}`).click();
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toBeVisible();
  // independent persistence after reload
  await page.reload();
  const after = await gwRead(page, `/gw/slots/${slot}/topic_item`);
  expect(after.b.head_revision as number, "the edit appended a new head revision").toBe(head0 + 1);
});

test("TOP-03 send-back records a decision and states the human commit floor", async ({ request, page }) => {
  const { rid, slot } = await topicReviewSlot(request, "372-top03");
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  await page.getByTestId(`wb-topic-item-comment-${slot}`).fill("اشرح الفكرة بوضوح أكبر");
  await page.getByTestId(`wb-topic-item-action-request_change-${slot}`).click();
  const msg = page.getByTestId(`wb-topic-item-write-msg-${slot}`);
  await expect(msg).toBeVisible();
  await expect(msg, "the UI states the decision is recorded and advances at the human commit").toContainText(/commit/i);
  // INDEPENDENT persistence after reload. NOTE the real read boundary: V2's /gw stage-state read is
  // allowlisted for `script_review` only (SERVED_GATES), so topic_review/state is refused by design.
  // The in-boundary evidence is the per-item read: a decision by THIS principal now exists, which is
  // exactly what makes the gate-scoped `undecide` available (#373's principal-bound projection).
  await page.reload();
  const item = await gwRead(page, `/gw/slots/${slot}/topic_item`);
  const acts = (item.b.actions ?? {}) as Record<string, { allowed: boolean; reason?: string }>;
  expect(acts.undecide?.allowed, "a decision by this principal persisted (undecide became available)").toBe(true);
});

test("TOP-05 Drop is RECORD-ONLY — a decision is recorded and the item does NOT transition", async ({ request, page }) => {
  const { rid, slot } = await topicReviewSlot(request, "372-top05");
  const status0 = ((await gwRead(await pageAt(page, `${WB_URL}/`), `/gw/slots/${slot}/topic_item`)).b.status) as string;
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  await page.getByTestId(`wb-topic-item-action-drop-${slot}`).click();
  const msg = page.getByTestId(`wb-topic-item-write-msg-${slot}`);
  await expect(msg).toBeVisible();
  await expect(msg, "the UI discloses the commit floor rather than claiming a committed drop").toContainText(/commit/i);
  // PRE-03: a decision exists, but V2 has NOT committed it — the item must not have transitioned.
  await page.reload();
  const after = await gwRead(page, `/gw/slots/${slot}/topic_item`);
  expect(after.b.status as string, "V2 never commits: the item is still in its review status").toBe(status0);
  // The decision IS recorded — evidenced in-boundary (topic stage-state is not on the V2 read
  // allowlist): a decision by this principal now exists, which is what makes `undecide` available.
  const acts = ((after.b.actions ?? {}) as Record<string, { allowed: boolean }>);
  expect(acts.undecide?.allowed, "the drop decision is recorded (undecide became available)").toBe(true);
});

// ---------------------------------------------------------------- Script
test("SCR-01 reach the Script workspace via the stage rail and expand a slot", async ({ request, page }) => {
  const { rid, slot } = await scriptReviewSlot(request, "372-scr01");
  await page.goto(`${WB_URL}/runs/${rid}`);
  await page.getByTestId("stage-script_review").click();
  await expect(page.getByTestId(`scripts-actions-${slot}`).or(page.getByTestId(`scripts-slot-toggle-${slot}`)),
    "the Script workspace renders the slot").toBeVisible({ timeout: 90_000 });
});

test("SCR-02 Script send-back through the visible control records a decision", async ({ request, page }) => {
  const { rid, slot } = await scriptReviewSlot(request, "372-scr02");
  await page.goto(`${WB_URL}/runs/${rid}?stage=script_review`);
  const toggle = page.getByTestId(`scripts-slot-toggle-${slot}`);
  await expect(toggle, "the slot expander renders").toBeVisible({ timeout: 90_000 });
  await toggle.click();
  await expect(page.getByTestId(`scripts-actions-${slot}`), "the lifecycle action surface renders").toBeVisible({ timeout: 60_000 });
  // A MANDATORY VALID row must actually EXERCISE the action: a typed-denied placeholder can NOT pass it.
  // If the server denies request_change on an eligible in-review script, this row FAILS loudly.
  const rc = page.getByTestId(`scripts-action-request_change-${slot}`);
  await expect(rc, "the Script send-back control is offered on an eligible in-review script").toBeVisible({ timeout: 60_000 });
  const input = page.getByTestId(`scripts-rc-comment-${slot}`);
  await expect(input, "the rationale input renders with the send-back control").toBeVisible();
  await input.fill("شدّ الافتتاحية");
  await expect(rc, "the control enables once a rationale is entered").toBeEnabled();
  await rc.click();
  await expect(page.getByTestId(`scripts-action-notice-${slot}`),
    "the governed send-back settled successfully (a typed refusal would surface here instead)").toBeVisible({ timeout: 30_000 });
  await page.reload();
  const st = await gwRead(page, `/gw/rounds/${rid}/stages/script_review/state`);
  expect(st.b.sent_back as number, "the Script send-back decision persisted (tally advanced)").toBeGreaterThan(0);
});

test("SCR-03 recovery control is a visible 'Reopen' 1:1 — and the Restore alias is absent (PRE-02)", async ({ request, page }) => {
  const { rid, slot } = await scriptReviewSlot(request, "372-scr03");
  // GOVERNED SETUP (PRE-01): commit a drop so `reopen` is genuinely ELIGIBLE — otherwise the control
  // would be typed-unavailable and this row could not assert the visible 1:1 label at all.
  await governedSetupCommitDrop(request, rid, slot, "script_review");
  await page.goto(`${WB_URL}/runs/${rid}?stage=script_review`);
  const toggle = page.getByTestId(`scripts-slot-toggle-${slot}`);
  await expect(toggle, "the slot expander renders").toBeVisible({ timeout: 90_000 });
  await toggle.click();
  await expect(page.getByTestId(`scripts-actions-${slot}`)).toBeVisible({ timeout: 60_000 });
  // POSITIVE half: the recovery control is VISIBLE and labelled 1:1 to the reopen endpoint.
  const reopen = page.getByTestId(`scripts-action-reopen-${slot}`);
  await expect(reopen, "the recovery control is rendered and visible").toBeVisible();
  await expect(reopen, "its label maps 1:1 to `reopen` — never 'Restore'").toHaveText(/Reopen/i);
  // NEGATIVE half: restore_revision is unrepresentable by design — no alias control exists.
  expect(await page.getByTestId(`scripts-action-restore-${slot}`).count(),
    "restore_revision is unrepresentable by design — no alias control exists").toBe(0);
});

// ---------------------------------------------------------------- Cross-cutting
test("XC-01 reload and navigate away/back preserve durable state", async ({ request, page }) => {
  const { rid, slot } = await topicReviewSlot(request, "372-xc01");
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  const head = ((await gwRead(page, `/gw/slots/${slot}/topic_item`)).b.head_revision) as number;
  await page.getByTestId("back-to-schedule").click();          // navigate away
  await page.waitForURL(/\/$|\/\?/, { timeout: 30_000 }).catch(() => {});
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`); // and back
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  expect(((await gwRead(page, `/gw/slots/${slot}/topic_item`)).b.head_revision) as number,
    "durable state is unchanged across navigation").toBe(head);
});

test("XC-02 direction and appearance toggles apply and persist across reload", async ({ request, page }) => {
  const rid = await scheduleOpenRun(request, "372-xc02");
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review&lens_${rid}=list`);
  await page.getByTestId("wb-dir-toggle").click();
  await expect(page.locator("html"), "direction flips to RTL").toHaveAttribute("dir", "rtl");
  await page.locator('[data-testid="wb-appearance"] button', { hasText: /dark/i }).first().click();
  await expect(page.locator("html"), "theme becomes dark").toHaveAttribute("data-theme", "dark");
  // OBSERVED TRUTH at this source: the THEME preference is persisted (pre-paint initializer +
  // data-theme), but DIRECTION is session-only — SSR re-seeds dir="ltr" on reload. This row asserts
  // what the product actually does; the direction-persistence shortfall is registered as GAP-06 and is
  // NOT counted as passed functionality (never relaxed into a false green).
  await page.reload();
  await expect(page.locator("html"), "theme persists across reload").toHaveAttribute("data-theme", "dark");
  await expect(page.locator("html"), "direction is session-only at this source (GAP-06)").toHaveAttribute("dir", "ltr");
});

/** helper: ensure the page has the workbench origin before a same-origin /gw read. */
async function pageAt(page: Page, url: string): Promise<Page> {
  if (!page.url().startsWith(WB_URL)) await page.goto(url);
  return page;
}

// SCH-05 (journey 3 refusal half + journey 10 stale-token/concurrency, GPT amendment: TRUE
// multi-context concurrency). Two independent browser CONTEXTS both load the same schedule; A commits
// a governed reorder through its visible control (advancing the token), then B — still holding the
// now-stale token it loaded — applies its own reorder through ITS visible control. B must be refused
// with a typed conflict and must NOT mutate the accepted order.
test("SCH-05 a stale-token reorder from a second context is refused, typed and non-mutating", async ({ request, browser }) => {
  const rid = await scheduleOpenRun(request, "372-sch05");
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const a = await ctxA.newPage();
  const b = await ctxB.newPage();
  const url = `${WB_URL}/runs/${rid}?stage=schedule_review&lens_${rid}=list`;
  await a.goto(url);
  await b.goto(url);                                   // B loads the CURRENT token, then goes stale
  await expect(a.getByTestId("schedule-cells")).toBeVisible({ timeout: 90_000 });
  await expect(b.getByTestId("schedule-cells")).toBeVisible({ timeout: 90_000 });

  // A commits a governed reorder — the schedule token advances underneath B.
  await a.locator('[data-testid^="cell-down-"]').first().click();
  await a.getByTestId("order-apply").click();
  await expect(a.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 30_000 });
  const accepted = await gwRead(a, `/gw/rounds/${rid}/schedule-mapping`);
  const acceptedCodes = ((accepted.b.positions || []) as { display_code: string }[]).map((p) => p.display_code).join(",");

  // B now applies its own reorder through its visible control, carrying the STALE token.
  await b.locator('[data-testid^="cell-down-"]').first().click();
  await b.getByTestId("order-apply").click();
  const fb = b.getByTestId("run-schedule-feedback");
  await expect(fb, "the stale reorder settles as a typed refusal, not a silent success").toHaveAttribute(
    "data-kind", /conflict|error/, { timeout: 30_000 });

  // NON-MUTATING: the accepted order is exactly what A committed.
  const final = await gwRead(a, `/gw/rounds/${rid}/schedule-mapping`);
  expect(((final.b.positions || []) as { display_code: string }[]).map((p) => p.display_code).join(","),
    "a refused stale reorder must not mutate the accepted order").toBe(acceptedCodes);
  await ctxA.close();
  await ctxB.close();
});
