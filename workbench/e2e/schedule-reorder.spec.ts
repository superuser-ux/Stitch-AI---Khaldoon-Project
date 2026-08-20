import { test, expect, type APIRequestContext } from "@playwright/test";
import { createHmac } from "node:crypto";
import { WB_URL, V1_URL, FIXTURE_ROUND } from "./surfaces";

// #292 — governed reorder on the V2 workbench, end to end against the real API.
//
// FIXTURE: RE2E is a LEGACY round (no mapping generation), so it cannot exercise reordering — that
// is the preservation-first design, not a gap. These specs therefore create a GOVERNED run through
// the same API an operator uses (POST /rounds), which gives it mapping generation 1 automatically.
// Synthetic, non-client, and never a reset of anything existing.

const API = process.env.API_BASE || "http://localhost:8009";

/** The gate API's trusted-principal contract. Used ONLY to arrange fixtures/conflicts here — V2's
 *  own signing stays server-side inside its route. */
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
  // 1 day x 3 posts = 3 slots, spread over whatever is eligible.
  const mix: Record<string, number> = {};
  for (let i = 0; i < 3; i++) mix[names[i % names.length]] = (mix[names[i % names.length]] || 0) + 1;
  const res = await request.post(`${API}/rounds`, {
    headers: signed(),
    data: { days: 1, posts_per_day: 3, label: "292-e2e", format_mix: mix },
  });
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()).round_id as string;
}

test.describe.configure({ mode: "serial" });

let ROUND = "";

test.beforeAll(async ({ playwright }) => {
  const request = await playwright.request.newContext();
  ROUND = await createGovernedRound(request);
  await request.dispose();
});

test("a NEW run is governed from birth: generation 1 with position-derived codes", async ({ request }) => {
  const m = await (await request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  expect(m.legacy).toBe(false);
  expect(m.schedule_token).toBe(1);
  expect(m.positions).toHaveLength(3);
  expect(m.positions.map((p: { display_position: number }) => p.display_position)).toEqual([1, 2, 3]);
  // posts_per_day=3 -> all three land on display day 01 with posts .01/.02/.03 (D-292-2 ruling).
  expect(m.positions.map((p: { display_code: string }) => p.display_code.slice(-5))).toEqual(
    ["01.01", "01.02", "01.03"],
  );
});

test("the LEGACY fixture round is untouched — no generation, no silent initialization", async ({ request }) => {
  const m = await (await request.get(`${WB_URL}/gw/rounds/${FIXTURE_ROUND}/schedule-mapping`)).json();
  expect(m.legacy).toBe(true);
  expect(m.schedule_token).toBe(0);
  expect(m.positions).toEqual([]);
});

// #331 — the governed #292 reorder now lives in the run's Coverage/Planning workspace
// (RunScheduleWorkspace), reached by navigating to the run and its default coverage stage. Same
// governed contract (canonical ids + accepted token, server decides, accepted order re-read, refusal
// surfaced) — proven here on the surviving surface.
test("operator reorders through V2: preview is distinct, commit renumbers codes, ids never move", async ({ page }) => {
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review&lens_${ROUND}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  const before = await (await page.request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  const first = before.positions[0].slot_id as string;
  const second = before.positions[1].slot_id as string;

  // Local preview is visibly NOT applied yet; the server token is unchanged while previewing.
  await page.getByTestId(`cell-down-${first}`).click();
  await expect(page.getByTestId("order-preview")).toBeVisible();
  const midToken = (await (await page.request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json()).schedule_token;
  expect(midToken, "previewing must not touch server state").toBe(1);

  await page.getByTestId("order-apply").click();
  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });
  await expect(page.getByTestId("order-preview")).toHaveCount(0);

  // Committed: a NEW generation, the codes follow POSITION, and canonical ids are untouched.
  const after = await (await page.request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  expect(after.schedule_token).toBe(2);
  expect(after.positions.map((p: { slot_id: string }) => p.slot_id).slice(0, 2)).toEqual([second, first]);
  expect(new Set(after.positions.map((p: { slot_id: string }) => p.slot_id)))
    .toEqual(new Set(before.positions.map((p: { slot_id: string }) => p.slot_id)));
  expect(after.positions.map((p: { display_code: string }) => p.display_code.slice(-5)))
    .toEqual(["01.01", "01.02", "01.03"]);
});

test("a concurrent accepted change makes the operator's commit fail truthfully with an explicit refresh", async ({ page, request }) => {
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ROUND)}?stage=schedule_review&lens_${ROUND}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  const m = await (await request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  const ids = m.positions.map((p: { slot_id: string }) => p.slot_id);

  // Stage a local preview at the CURRENT token...
  await page.getByTestId(`cell-down-${ids[0]}`).click();
  await expect(page.getByTestId("order-preview")).toBeVisible();

  // ...then someone else commits an accepted reorder first. Real API call, not a mock: the page's
  // held token is now genuinely stale.
  const other = await request.post(`${API}/rounds/${ROUND}/schedule-reorder`, {
    headers: signed(),
    data: { order: [ids[2], ids[1], ids[0]], schedule_token: m.schedule_token },
  });
  expect(other.status()).toBe(200);

  await page.getByTestId("order-apply").click();

  // Truthful conflict: NOT applied, NOT silently reconciled, resolved only by explicit refresh.
  const feedback = page.getByTestId("run-schedule-feedback");
  await expect(feedback).toHaveAttribute("data-kind", "conflict", { timeout: 20_000 });
  await expect(feedback).toContainText("changed while you were reordering");
  const server = await (await request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  expect(server.positions.map((p: { slot_id: string }) => p.slot_id), "the loser must not overwrite")
    .toEqual([ids[2], ids[1], ids[0]]);

  // The stale preview is already discarded (the 409 reverted to authoritative order); refresh clears
  // the conflict notice and re-reads server truth.
  await expect(page.getByTestId("order-preview")).toHaveCount(0);
  await page.getByTestId("run-schedule-refresh").click();
  await expect(feedback).toHaveAttribute("data-kind", "idle");
});

test("V1 still reads the same governed run and prefers the server code (no divergence)", async ({ request }) => {
  // V1 and V2 must not show two different human-facing codes for one canonical slot.
  const v2 = await (await request.get(`${WB_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  const v1 = await (await request.get(`${V1_URL}/gw/rounds/${ROUND}/schedule-mapping`)).json();
  expect(v1.schedule_token).toBe(v2.schedule_token);
  expect(v1.positions).toEqual(v2.positions);
});
