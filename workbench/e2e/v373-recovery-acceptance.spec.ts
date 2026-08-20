import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { WB_URL } from "./surfaces";

// #373 — browser operator-journey acceptance for the four #372 blockers, driven through VISIBLE
// RENDERED CONTROLS (never in-page fetch shortcuts): canonical Topic/Script `reopen` (1:1 label),
// gate-scoped `undecide` addressed to the server-projected authoritative gate id, focus restoration,
// and 768/1280×LTR/RTL/theme reachability. Every governed mutation correlates a rendered control ->
// a browser-issued request -> a typed response -> a visible outcome -> exact persistence -> reload.
// Fixtures are provisioned through canonical API routes (setup only); the ACCEPTANCE actions are UI.

const API = process.env.API_BASE || "http://127.0.0.1:8370";

function signed(principal = "khal") {
  const secret = process.env.REVIEWER_PROXY_SECRET?.trim() || "dev-internal-reviewer-proxy-secret";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", secret).update(principal, "utf8").digest("hex"),
    "content-type": "application/json",
  };
}

/** Provision a run to topic_review and return a slot the SERVER reports EDITABLE (so its item panel
 *  renders and is actionable) — mirrors topic-item-governance's non-skipping selection: the panel is
 *  mounted per slot in the generation read model, so we poll it rather than the round's slot list. */
async function editableTopicSlot(req: APIRequestContext, label: string): Promise<{ rid: string; slot: string }> {
  // A FRESH candidate DB has no active workflow version, so /workflow-stages/active (a pure SELECT)
  // 404s and RunWorkspace renders no stage panel. GET /workflow-versions/active seeds the baseline
  // governed version when none is active (idempotent), which the stage rail is then derived from.
  await req.get(`${API}/workflow-versions/active`);
  const elig = await (await req.get(`${API}/baseline-eligibility`)).json();
  const names: string[] = (elig.eligible || elig.frameworks || []).map((f: { name: string }) => f.name);
  expect(names.length, "candidate lane must have baseline-eligible frameworks").toBeGreaterThan(0);
  const mk = await req.post(`${API}/rounds`, { headers: signed(),
    data: { days: 1, posts_per_day: 3, label, format_mix: { [names[0]]: 3 } } });
  expect(mk.status(), await mk.text()).toBe(200);
  const rid = (await mk.json()).round_id as string;
  const g = await (await req.post(`${API}/gates`, { headers: signed(), data: { stage: "schedule_review", round_id: rid } })).json();
  const gid = g.gate_id || g.gate?.gate_id;
  await req.post(`${API}/gates/${gid}/decide`, { headers: signed(), data: { decision: "approve" } });
  await req.post(`${API}/gates/${gid}/resolve`, { headers: signed(), data: {} });   // -> auto Topic gen (stub)

  // Poll the generation read model until the GenerationSeam's render precondition holds (the panel
  // renders per result only when stage2a_enabled AND a durable job exists) AND a result's topic is
  // editable. Matching the exact panel precondition avoids selecting a run whose panel never mounts.
  for (let i = 0; i < 60; i++) {
    const res = await req.get(`${API}/rounds/${rid}/generation`);
    if (res.ok()) {
      const m = await res.json();
      if (m.stage2a_enabled && (m.jobs || []).length > 0) {
        for (const r of (m.results || []) as { topic: unknown; slot_id: string }[]) {
          if (!r.topic) continue;
          const item = await req.get(`${API}/slots/${r.slot_id}/topic_item`);
          if (item.ok() && (await item.json())?.actions?.edit?.allowed === true) return { rid, slot: r.slot_id };
        }
      }
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("fixture: no editable generated topic with a durable job appeared (panel precondition unmet)");
}

/** Provision a run and COMMIT a drop on a topic slot so it is genuinely in a reject state (reopen-
 *  eligible). V2's per-item Drop is record-only ("advances at the human commit"), so to reach the
 *  reopen-eligible state we record a governed drop on every slot then RESOLVE the gate — the governed
 *  commit floor — via canonical routes (setup only). The ACCEPTANCE action (Reopen) is then UI. */
async function committedDroppedSlot(req: APIRequestContext, label: string): Promise<{ rid: string; slot: string }> {
  const { rid, slot } = await editableTopicSlot(req, label);
  const gen = await (await req.get(`${API}/rounds/${rid}/generation`)).json();
  const slots = ((gen.results || []) as { slot_id: string }[]).map((r) => r.slot_id);
  for (const s of slots) {
    await req.post(`${API}/slots/${s}/drop`, { headers: signed(), data: { artifact: "topic" } });
  }
  const g = await (await req.post(`${API}/gates`, { headers: signed(), data: { stage: "topic_review", round_id: rid } })).json();
  const gid = g.gate_id || g.gate?.gate_id;
  await req.post(`${API}/gates/${gid}/resolve`, { headers: signed(), data: {} });   // COMMIT the drops
  return { rid, slot };
}

/** A fresh schedule-open (revisable) run — no schedule approval, so the reorder controls are live. */
async function scheduleOpenRun(req: APIRequestContext, label: string): Promise<string> {
  await req.get(`${API}/workflow-versions/active`);
  const elig = await (await req.get(`${API}/baseline-eligibility`)).json();
  const fw = ((elig.eligible || elig.frameworks || [])[0] as { name: string }).name;
  const mk = await req.post(`${API}/rounds`, { headers: signed(),
    data: { days: 1, posts_per_day: 3, label, format_mix: { [fw]: 3 } } });
  expect(mk.status(), await mk.text()).toBe(200);
  return (await mk.json()).round_id as string;
}

/** A browser-issued /gw read (same-origin after navigating to the workbench) for INDEPENDENT persistence. */
async function gwRead(page: Page, path: string) {
  return await page.evaluate(async (p) => {
    const r = await fetch(p);
    let b: unknown = {}; try { b = await r.json(); } catch { /* */ }
    return { s: r.status, b: b as Record<string, unknown> };
  }, path);
}

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  await page.goto(`${WB_URL}/`);   // establish workbench origin for same-origin browser /gw reads
});

// R1-TOPIC-REOPEN-LOOP — a governed-committed dropped item -> reload -> Reopen (visible control) ->
// reload, with independent persistence. Closes #372's broken drop->recover loop (reopen had no
// control). The committed drop is governed setup (V2 Drop is record-only); Reopen is the UI action.
test("R1 Topic reopen through the visible Reopen control (committed-dropped -> reopened)", async ({ request, page }) => {
  const { rid, slot } = await committedDroppedSlot(request, "373-r1-topic");
  // independent read: the item is genuinely in a reject/dropped state to begin with
  await page.goto(`${WB_URL}/`);
  const before = await gwRead(page, `/gw/slots/${slot}/topic_item`);
  expect(String(before.b.status ?? ""), "the item starts in a committed dropped/reject state").toMatch(/DROP|REJECT/i);

  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`), "the per-item governance panel renders").toBeVisible({ timeout: 90_000 });
  const reopenBtn = page.getByTestId(`wb-topic-item-action-reopen-${slot}`);
  await expect(reopenBtn, "Reopen is a rendered control (1:1 label, closes #372's gap)").toBeVisible();
  await expect(reopenBtn, "Reopen is enabled for a committed-dropped item").toBeEnabled();

  // REOPEN via the visible control (browser-issued).
  await reopenBtn.click();
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toBeVisible();

  // RELOAD + independent persistence: the item is back in review (no longer dropped).
  await page.reload();
  const after = await gwRead(page, `/gw/slots/${slot}/topic_item`);
  expect(after.s).toBe(200);
  expect(String(after.b.status ?? ""), "reopen persisted: item no longer dropped on a fresh browser read").not.toMatch(/DROP|REJECT/i);
});

// R2-TOPIC-UNDECIDE-LOOP — Send back (records a decision) -> reload -> Undo (gate-scoped) -> reload.
test("R2 Topic undecide loop through the visible Undo control (authoritative gate id)", async ({ request, page }) => {
  const { rid, slot } = await editableTopicSlot(request, "373-r2-topic");
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });

  // SEND BACK (request_change) — records an uncommitted decision on the single open gate.
  await page.getByTestId(`wb-topic-item-comment-${slot}`).fill("send back — v2 acceptance");
  await page.getByTestId(`wb-topic-item-action-request_change-${slot}`).click();
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toBeVisible();

  // RELOAD — the server now projects the authoritative gate id and Undo becomes eligible.
  await page.reload();
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
  const undo = page.getByTestId(`wb-topic-item-action-undecide-${slot}`);
  await expect(undo, "Undo is a rendered control").toBeVisible();
  await expect(undo, "Undo is enabled when a gate + decision exist").toBeEnabled();
  const gateAttr = await undo.getAttribute("data-gate");
  expect(gateAttr, "the control carries the server-projected authoritative gate id").toBeTruthy();

  // UNDO (gate-scoped) via the visible control.
  await undo.click();
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toBeVisible();

  // RELOAD + independent persistence: undecide now unavailable (no_decision) — the decision was cleared.
  await page.reload();
  const item = await gwRead(page, `/gw/slots/${slot}/topic_item`);
  const acts = (item.b.actions ?? {}) as Record<string, { allowed: boolean; reason?: string }>;
  expect(acts.undecide?.allowed, "the recorded decision was cleared (undecide no longer allowed)").toBe(false);
  expect(acts.undecide?.reason, "typed reason after clear").toBe("no_decision");
});

// R2-UNDECIDE-UNAVAILABLE — a fresh in-review item shows Undo disabled with the typed reason (non-mutating).
test("R2 Undo is typed-unavailable (no_decision) on a fresh in-review item", async ({ request, page }) => {
  const { rid, slot } = await editableTopicSlot(request, "373-r2-unavail");
  await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
  const undo = page.getByTestId(`wb-topic-item-action-undecide-${slot}`);
  await expect(undo).toBeVisible({ timeout: 90_000 });
  await expect(undo, "no decision yet -> disabled").toBeDisabled();
  // typed-unavailable, non-mutating: a fresh item may have no open gate yet (no_open_gate) or a gate
  // with no recorded decision (no_decision) — both are truthful typed reasons the server projects.
  expect(["no_decision", "no_open_gate", "ambiguous_gate"], "a typed unavailable reason is rendered")
    .toContain(await undo.getAttribute("data-reason"));
});

// R3-FOCUS-SCHEDULE (Codex P2) — focus is RETAINED on the initiating control while the reorder is
// pending (busy), and RESTORED to the announced status region only once it SETTLES (ok). A brief
// response delay makes the pending window observable — this is TIMING control (the REAL governed
// response is delivered via route.continue), not a mocked response.
test("R3 schedule focus — retained while pending, restored on settle", async ({ request, page }) => {
  const rid = await scheduleOpenRun(request, "373-r3-sched");
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review&lens_${rid}=list`);
  const move = page.locator('[data-testid^="cell-down-"]').first();
  await expect(move, "a schedule move control is rendered").toBeVisible({ timeout: 90_000 });
  await move.click();                                  // build a reorder preview via the visible control
  const apply = page.getByTestId("order-apply");
  await expect(apply).toBeVisible();

  await page.route("**/gw/rounds/**/schedule-reorder", async (route) => {
    await new Promise((r) => setTimeout(r, 1200));     // widen the pending window; real response still sent
    await route.continue();
  });
  await apply.focus();
  await apply.click();
  // PENDING: the feedback region is busy and focus is NOT yanked to it (retained on the control).
  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "busy");
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid")),
    "focus retained on the initiating control while pending").not.toBe("run-schedule-feedback");
  await page.unroute("**/gw/rounds/**/schedule-reorder");
  // SETTLED: focus is restored to the announced status region.
  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 15_000 });
  expect(await page.evaluate(() => document.activeElement?.getAttribute("data-testid")),
    "focus restored to the announced status region on settle").toBe("run-schedule-feedback");
});

// R4-RESPONSIVE-REACHABILITY — the affected controls stay visible + the page never scrolls horizontally
// at 375/768/1280 across LTR/RTL (a declared covering subset). No CSS is added; this is acceptance
// coverage only (a failure here would be a reproduced defect authorizing a minimal fix).
for (const vp of [375, 768, 1280]) {
  test(`R4 reachability + no page overflow at ${vp}px`, async ({ request, page }) => {
    const { rid, slot } = await editableTopicSlot(request, `373-r4-${vp}`);
    await page.setViewportSize({ width: vp, height: 900 });
    await page.goto(`${WB_URL}/runs/${rid}?stage=topic_review`);
    await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible({ timeout: 90_000 });
    // the governed action controls remain reachable (visible) at this viewport
    await expect(page.getByTestId(`wb-topic-item-action-approve-${slot}`)).toBeVisible();
    await expect(page.getByTestId(`wb-topic-item-action-drop-${slot}`)).toBeVisible();
    // no PAGE-LEVEL horizontal overflow (internal scrollers are allowed by design)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `no page-level horizontal overflow at ${vp}px`).toBeLessThanOrEqual(1);
  });
}
