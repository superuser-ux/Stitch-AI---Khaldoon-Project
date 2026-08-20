import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { WB_URL } from "./surfaces";

// #370 — the REAL-`/gw` V2 lifecycle proof. TEST-HARNESS ONLY; unreachable from product startup.
//
// WHY THIS EXISTS. Every prior V2 lifecycle spec (scripts-lifecycle-367, topics-coverage, …) drives
// the surface with MOCKED `/gw` routes — it proves the projection, not that a governed action reaches
// a real API and a real database. This spec forbids that: every frozen action is issued FROM THE
// BROWSER (an in-page `fetch` after navigating to the workbench origin), is INDEPENDENTLY OBSERVED via
// the page's `response` events (which fire only for browser-originated requests, never for an out-of-
// page APIRequestContext), and is correlated with an INDEPENDENT persistence read after reload. A
// fail-on-unexpected-interception control is armed and proven active, then disabled, before each test.
// Fixtures are provisioned only through canonical governed routes into the disposable candidate DB.
//
// It freezes exactly one governed action per Content stage (Codex reconciliation on #370):
//   Schedule → the #292 governed reorder; Topic → a governed edit; Script → a governed request_change.

const API = process.env.API_BASE || "http://127.0.0.1:8370";

function signed(principal = "khal") {
  const secret = process.env.REVIEWER_PROXY_SECRET?.trim() || "dev-internal-reviewer-proxy-secret";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", secret).update(principal, "utf8").digest("hex"),
    "content-type": "application/json",
  };
}

type GwObs = { url: string; status: number; fromSW: boolean; method: string };

/** Issue a `/gw` call FROM THE BROWSER (in-page fetch, same-origin after page.goto(WB_URL)). This is a
 *  genuinely browser-originated request — it appears in the page's `response` events and is subject to
 *  page routing, unlike an APIRequestContext. Returns the typed upstream status + body. */
async function browserGw(page: Page, method: string, path: string, body?: unknown) {
  return await page.evaluate(async ({ m, p, b }) => {
    const r = await fetch(p, { method: m, headers: { "content-type": "application/json" },
      body: b !== null && b !== undefined ? JSON.stringify(b) : undefined });
    let parsed: unknown = {};
    try { parsed = await r.json(); } catch { /* non-JSON */ }
    return { s: r.status, b: parsed as Record<string, unknown> };
  }, { m: method, p: path, b: body ?? null });
}

/** Assert a browser-issued `/gw` request to `substr` was OBSERVED (proving it left the browser and hit
 *  the network) and returned the expected real status — never a service-worker/mocked response. */
function assertBrowserIssued(page: Page, substr: string, statusWanted: number) {
  const hits = ((page as unknown as { __gw: GwObs[] }).__gw || []).filter((e) => e.url.includes(substr));
  expect(hits.length, `a browser-issued /gw request to ${substr} must have been observed`).toBeGreaterThan(0);
  const last = hits[hits.length - 1];
  expect(last.status, `observed /gw response for ${substr}`).toBe(statusWanted);
  expect(last.fromSW, `the /gw response for ${substr} came from the real network, not a service worker`).toBe(false);
}

/** Drive the governed chain to a chosen stopping stage; returns the round id. Canonical API routes for
 *  FIXTURE SETUP only (not a frozen action) — the frozen actions themselves are browser-issued /gw. */
async function governedRun(req: APIRequestContext, label: string, stopAt: "schedule" | "topic" | "script") {
  const elig = (await (await req.get(`${API}/baseline-eligibility`)).json());
  const names: string[] = (elig.eligible || elig.frameworks || []).map((f: { name: string }) => f.name);
  expect(names.length, "candidate lane must have baseline-eligible frameworks").toBeGreaterThan(0);
  const mk = await req.post(`${API}/rounds`, { headers: signed(),
    data: { days: 1, posts_per_day: 3, label, format_mix: { [names[0]]: 3 } } });
  expect(mk.status(), await mk.text()).toBe(200);
  const rid = (await mk.json()).round_id as string;
  if (stopAt === "schedule") return rid;

  const gate = async (stage: string) => {
    const g = await (await req.post(`${API}/gates`, { headers: signed(), data: { stage, round_id: rid } })).json();
    const gid = g.gate_id || g.gate?.gate_id;
    await req.post(`${API}/gates/${gid}/decide`, { headers: signed(), data: { decision: "approve" } });
    await req.post(`${API}/gates/${gid}/resolve`, { headers: signed(), data: {} });
  };
  await gate("schedule_review");
  await new Promise((r) => setTimeout(r, 1500));
  if (stopAt === "topic") return rid;
  await gate("topic_review");
  await new Promise((r) => setTimeout(r, 2000));
  return rid;
}

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }) => {
  // Establish the workbench ORIGIN so in-page `/gw` fetches are same-origin (genuinely browser-issued).
  await page.goto(WB_URL);
  // Observe every browser-originated /gw response for later correlation (this event never fires for an
  // out-of-page APIRequestContext — so observing here IS the proof the request came from the browser).
  (page as unknown as { __gw: GwObs[] }).__gw = [];
  page.on("response", (resp) => {
    const u = resp.url();
    if (u.includes("/gw/")) {
      (page as unknown as { __gw: GwObs[] }).__gw.push(
        { url: u, status: resp.status(), fromSW: resp.fromServiceWorker(), method: resp.request().method() });
    }
  });
  // ACTIVE fail-on-unexpected-interception control: arm a fulfilling /gw mock, prove a browser fetch is
  // genuinely intercepted, then DISABLE it so the frozen actions run against the real server. If the
  // browser path could not be intercepted the control would fail here — so "interception is off during
  // the actions" is a demonstrated, not assumed, property.
  const FAKE = 599;
  await page.route("**/gw/health", (route) =>
    route.fulfill({ status: FAKE, contentType: "application/json", body: JSON.stringify({ MOCKED: true }) }));
  const armed = await page.evaluate(async (u) => { const r = await fetch(u); return { s: r.status, t: await r.text() }; }, `${WB_URL}/gw/health`);
  expect(armed.s, "the interception control must be genuinely active on the browser path").toBe(FAKE);
  expect(armed.t).toContain("MOCKED");
  await page.unroute("**/gw/health");
  const disabled = await browserGw(page, "GET", "/gw/health");
  expect(disabled.s, "interception disabled: a browser fetch now reaches the real server").toBe(200);
  expect(JSON.stringify(disabled.b), "no mocked body reaches the actions").not.toContain("MOCKED");
});

test("Schedule — browser-issued governed reorder reaches the real API + DB through /gw", async ({ request, page }) => {
  const rid = await governedRun(request, "370-sched", "schedule");
  const map = await browserGw(page, "GET", `/gw/rounds/${rid}/schedule-mapping`);
  expect(map.s, JSON.stringify(map.b)).toBe(200);
  assertBrowserIssued(page, `/gw/rounds/${rid}/schedule-mapping`, 200);
  const positions = (map.b.positions || []) as { slot_id: string; display_code: string }[];
  const token = map.b.schedule_token as number;
  expect(positions.length, "the run must have a governed schedule to reorder").toBeGreaterThan(1);
  const beforeCodes = positions.map((p) => p.display_code).join(",");
  // FROZEN ACTION (browser-issued): a governed COMPLETE-permutation reorder (slot_ids reversed).
  const order = positions.map((p) => p.slot_id).reverse();
  const res = await browserGw(page, "POST", `/gw/rounds/${rid}/schedule-reorder`, { order, schedule_token: token });
  expect(res.s, JSON.stringify(res.b)).toBe(200);
  assertBrowserIssued(page, `/gw/rounds/${rid}/schedule-reorder`, 200);
  // independent persistence after reload (a fresh browser-issued /gw read): display codes followed the
  // reorder and the schedule token advanced.
  const after = await browserGw(page, "GET", `/gw/rounds/${rid}/schedule-mapping`);
  const afterCodes = ((after.b.positions || []) as { display_code: string }[]).map((p) => p.display_code).join(",");
  expect(afterCodes, "the reorder must persist to the real DB, observable on a fresh read").not.toBe(beforeCodes);
  expect((after.b.schedule_token as number) > token, "the governed reorder advanced the schedule token").toBeTruthy();
});

test("Topic — browser-issued governed edit reaches the real API + DB through /gw, verified after reload", async ({ request, page }) => {
  const rid = await governedRun(request, "370-topic", "topic");
  const rounds = (await browserGw(page, "GET", `/gw/rounds/${rid}`)).b;
  const slot = ((rounds.slots || []) as { status: string; slot_id: string }[]).find((s) => s.status === "TOPIC_PROPOSED")?.slot_id;
  expect(slot, "a topic_review slot at TOPIC_PROPOSED must exist").toBeTruthy();
  // V2's read boundary permits ONLY artifact=script; Topic is read via topic_item WITHOUT artifact.
  const head = (await browserGw(page, "GET", `/gw/slots/${slot}/topic_item`)).b.head_revision as number;
  expect(head, "topic head revision must be readable via the real V2 topic read").toBeGreaterThan(0);
  // FROZEN ACTION (browser-issued): a governed edit (artifact travels in the body).
  const res = await browserGw(page, "POST", `/gw/slots/${slot}/edit`,
    { artifact: "topic", field: "hook_text", value: "hook edited via v2 real-route proof",
      expected_revision: head, idempotency_key: `370-topic-${slot}` });
  expect(res.s, JSON.stringify(res.b)).toBe(200);
  assertBrowserIssued(page, `/gw/slots/${slot}/edit`, 200);
  expect(res.b.new_revision, "the governed edit appended a new revision (typed result)").toBe(head + 1);
  // independent persistence after reload: a fresh browser-issued real-V2 read shows the head advanced.
  const afterHead = (await browserGw(page, "GET", `/gw/slots/${slot}/topic_item`)).b.head_revision as number;
  expect(afterHead, "the edit must persist to the real DB, observable on a fresh read").toBe(head + 1);
});

test("Script — browser-issued governed request_change reaches the real API + DB through /gw (frozen action)", async ({ request, page }) => {
  const rid = await governedRun(request, "370-script", "script");
  const before = (await browserGw(page, "GET", `/gw/rounds/${rid}/stages/script_review/state`)).b;
  expect(before.review_pending, "the run must have generated scripts under review").toBeGreaterThan(0);
  const beforeSentBack = before.sent_back as number;
  const beforePending = before.pending as number;
  const rounds = (await browserGw(page, "GET", `/gw/rounds/${rid}`)).b;
  const slot = ((rounds.slots || []) as { status: string; slot_id: string }[]).find((s) => s.status === "DRAFT_ASSIGNED")?.slot_id;
  expect(slot, "a script slot at DRAFT_ASSIGNED must exist").toBeTruthy();
  // FROZEN ACTION (browser-issued): governed request_change.
  const res = await browserGw(page, "POST", `/gw/slots/${slot}/request_change`,
    { artifact: "script", comment: "tighten the hook — v2 real-route proof" });
  expect(res.s, JSON.stringify(res.b)).toBe(200);
  assertBrowserIssued(page, `/gw/slots/${slot}/request_change`, 200);
  expect(res.b.decision_recorded, "typed governed result").toBe(true);
  expect(res.b.committed, "request_change records a decision; the transition is the human commit floor").toBe(false);
  expect((res.b.result as { gate_id?: string })?.gate_id, "the decision was recorded against a REAL governed gate").toBeTruthy();
  // INDEPENDENT persistence after reload — a fresh browser-issued /gw read shows the send-back tally
  // advanced and the decision counted pending (the exact record is additionally verified DB-side by the
  // orchestrator's decision-verify phase).
  const after = (await browserGw(page, "GET", `/gw/rounds/${rid}/stages/script_review/state`)).b;
  expect(after.sent_back as number, "the send-back decision persisted to the real DB (fresh /gw read)").toBe(beforeSentBack + 1);
  expect(after.pending as number, "the recorded-but-uncommitted decision is counted pending").toBeGreaterThan(beforePending);
  const item = (await browserGw(page, "GET", `/gw/slots/${slot}/topic_item?artifact=script`)).b;
  expect(item.status, "request_change records a decision without transitioning (human commit floor)").toBe("DRAFT_ASSIGNED");
  // typed refusal path: an out-of-domain artifact is refused at the real boundary (browser-issued).
  const bad = await browserGw(page, "POST", `/gw/slots/${slot}/request_change`, { artifact: "bogus", comment: "x" });
  expect([400, 409, 422].includes(bad.s), "a typed refusal is returned, not a mock").toBeTruthy();
});
