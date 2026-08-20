import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { WB_URL } from "./surfaces";

// #376 — calendar-first run planning + governed mix recommendation acceptance.
//
// BINDING RULINGS (Codex reconciliation on #376, implemented literally here):
//  A  The rail consumes the CANONICAL ACTIVE-STAGE PROJECTION. STG-01 reads BOTH governed endpoints so
//     "absent" is proven to mean "the generation disabled it", never "it was never declared" and never
//     "a client filtered it out".
//  B  Production terminology is ONE governed `stage_label` — `Approved for production` — established
//     through draft → update → activate. No frontend alias, no derived completion string.
//  C  The commit floor stays out of scope. Nothing here implements, claims or asserts a browser
//     commit/resolve/advance control. GAP-02 is the mechanism; GAP-07 its human-UAT consequence.
//  D  MIX-03 and MIX-01 run on DELIBERATELY DISTINCT governed setup — MIX-03 FIRST with no current
//     recommendation-policy generation, MIX-01 after one is minted. Test order is therefore load-
//     bearing and this file runs serially.
//  E  The retained human lane is created separately, only after this matrix passes.
//
// Every row is driven through VISIBLE RENDERED CONTROLS and correlated with an INDEPENDENT
// browser-issued persistence read. Titles carry the matrix row id so evidence joins ID → result.

const API = process.env.API_BASE || "http://127.0.0.1:8391";

function signed(principal = "khal") {
  const secret = process.env.REVIEWER_PROXY_SECRET?.trim() || "dev-internal-reviewer-proxy-secret";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", secret).update(principal, "utf8").digest("hex"),
    "content-type": "application/json",
  };
}

/** A browser-issued /gw read (same-origin) — INDEPENDENT persistence evidence. */
async function gwRead(page: Page, path: string) {
  return await page.evaluate(async (p) => {
    const r = await fetch(p);
    let b: unknown = {}; try { b = await r.json(); } catch { /* */ }
    return { s: r.status, b: b as Record<string, unknown> };
  }, path);
}

/** Durable state that a mere date gesture must NOT create. Read through the browser, so the evidence
 *  is the same boundary the operator's session uses. */
async function durableState(page: Page) {
  const runs = await gwRead(page, "/gw/rounds");
  return {
    runIds: ((runs.b as unknown as { round_id: string }[]) || []).map((r) => r.round_id).sort(),
  };
}

/** GOVERNED SETUP (ruling D) — mint a CURRENT run-mix recommendation-policy generation through the
 *  authority's OWN authorized administration path. Never a browser control, never a seed rewrite:
 *  #377 supersedes the previous generation rather than editing it. */
async function governedSetupRunMixPolicy(req: APIRequestContext) {
  const elig = await (await req.get(`${API}/baseline-eligibility`)).json();
  const eligible = (elig.eligible || elig.frameworks || []) as { name: string; version_id: string }[];
  expect(eligible.length, "the lane must offer baseline-eligible frameworks").toBeGreaterThan(0);
  const weights: Record<string, number> = {};
  for (const f of eligible) weights[f.version_id] = 1;      // keyed by VERSION id, never by name
  const res = await req.post(`${API}/run-mix-policy`, { headers: signed(), data: { weights, notes: "#376 matrix" } });
  expect(res.status(), await res.text()).toBe(200);
  const cur = await (await req.get(`${API}/run-mix-policy`)).json();
  expect(cur.status, "a current recommendation-policy generation now exists").toBe("current");
  return eligible.map((f) => f.name);
}

test.describe.configure({ mode: "serial" });

// ------------------------------------------------------------------ lane shape
test("FIX-01 the lane starts genuinely clean: zero runs, a valid active generation, real eligibility", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  const runs = await gwRead(page, "/gw/rounds");
  expect(runs.s).toBe(200);
  expect((runs.b as unknown as unknown[]).length, "a clean lane carries NO runs").toBe(0);

  const proj = await gwRead(page, "/gw/workflow-stages/active-enabled");
  expect(proj.s, "an active governed generation exists").toBe(200);
  expect(((proj.b.stages || []) as unknown[]).length, "the generation declares navigable stages").toBeGreaterThan(0);

  const elig = await gwRead(page, "/gw/baseline-eligibility");
  expect(elig.s).toBe(200);
  expect(((elig.b.eligible || []) as unknown[]).length, "baseline eligibility offers frameworks").toBeGreaterThan(0);
});

// ------------------------------------------------------------------ calendar-first composition
test("CAL-01 the root opens on the runs calendar even with zero runs", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  // The calendar itself renders — the old behaviour replaced the whole workspace with a text card, so
  // a fresh lane had no schedule to start a run from. Emptiness is STATED ALONGSIDE the grid.
  await expect(page.getByTestId("runs-calendar"), "the calendar workspace renders").toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("runs-calendar-grid")).toBeVisible();
  await expect(page.getByTestId("runs-calendar-empty"), "zero runs is stated, not hidden").toBeVisible();
  await expect(page.getByTestId("new-run"), "the third entry path is present").toBeVisible();
});

test("CAL-02 a date click initializes a one-day draft and writes NOTHING", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("runs-calendar-grid")).toBeVisible({ timeout: 60_000 });
  const before = await durableState(page);

  // Drive the REAL rendered calendar cell — not a synthetic event. Day cells are addressed by the
  // calendar's own `data-date`, which is stable public output; the v7 CSS class names are hashed and
  // would be a brittle internal coupling.
  const cells = page.locator('[data-testid="runs-calendar-grid"] [data-date]');
  expect(await cells.count(), "the month grid renders addressable day cells").toBeGreaterThan(0);
  const clicked = await cells.nth(8).getAttribute("data-date");
  await cells.nth(8).click();

  const composer = page.getByTestId("run-composer");
  await expect(composer, "the composer opened from the calendar gesture").toBeVisible({ timeout: 30_000 });
  await expect(composer).toHaveAttribute("data-source", "date-click");
  const starts = await composer.getAttribute("data-starts-on");
  const ends = await composer.getAttribute("data-ends-on");
  expect(starts, "the draft starts on the date that was actually clicked").toBe(clicked);
  expect(starts, "a clicked date is a ONE-DAY inclusive range").toBe(ends);
  await expect(composer).toHaveAttribute("data-days", "1");

  const after = await durableState(page);
  expect(after.runIds, "ZERO durable writes: the run set is unchanged by a date click").toEqual(before.runIds);
  // Nothing was recommended either, so no proposal fence can exist yet.
  await expect(page.getByTestId("composer-mix"), "no mix is presented before the authority answers")
    .toHaveAttribute("data-state", "none");
  await expect(page.getByTestId("composer-submit"), "submit is disabled without a governed recommendation").toBeDisabled();
});

test("CAL-03 an inclusive range selection sets the duration and previews the plan, writing NOTHING", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("runs-calendar-grid")).toBeVisible({ timeout: 60_000 });
  const before = await durableState(page);

  // A real drag-select across three day cells of the rendered month grid.
  const cells = page.locator('[data-testid="runs-calendar-grid"] [data-date]');
  const a = await cells.nth(7).boundingBox();
  const b = await cells.nth(9).boundingBox();
  expect(a && b, "the month grid renders selectable day cells").toBeTruthy();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, { steps: 8 });
  await page.mouse.up();

  const composer = page.getByTestId("run-composer");
  await expect(composer, "the range gesture opened the SAME composer").toBeVisible({ timeout: 30_000 });
  await expect(composer).toHaveAttribute("data-source", "range");
  const days = Number(await composer.getAttribute("data-days"));
  expect(days, "the inclusive range defines the duration").toBe(3);

  // The preview reconciles the range with posts/day into an expected slot count (GPT amendment 5).
  await page.getByTestId("composer-posts").fill("2");
  await expect(page.getByTestId("composer-preview-slots")).toContainText("6 slots");
  await expect(composer).toHaveAttribute("data-expected-slots", "6");
  await expect(page.getByTestId("composer-preview-coverage"), "the covered dates are shown").toBeVisible();

  const after = await durableState(page);
  expect(after.runIds, "ZERO durable writes: range selection creates nothing").toEqual(before.runIds);
});

// ------------------------------------------------------------------ governed recommendation
test("MIX-03 with NO current policy generation the recommendation is typed-blocked and submit stays disabled", async ({ page }) => {
  // Ruling D: this row's precondition is the ABSENCE of a current generation. It runs before any is
  // minted, so the blocked state is real rather than simulated.
  await page.goto(`${WB_URL}/`);
  await page.getByTestId("new-run").click();
  const composer = page.getByTestId("run-composer");
  await expect(composer).toBeVisible();
  await expect(composer).toHaveAttribute("data-source", "new-run");

  await page.getByTestId("composer-recommend").click();

  const blocked = page.getByTestId("composer-mix-blocked");
  await expect(blocked, "the typed blocked state is displayed").toBeVisible({ timeout: 30_000 });
  await expect(blocked).toHaveAttribute("data-reason", "no_current_recommendation_policy");
  await expect(page.getByTestId("composer-submit"), "durable submit is DISABLED while blocked").toBeDisabled();
  // The draft survives the refusal — nothing the operator chose is discarded.
  await expect(composer).toHaveAttribute("data-days", "7");
  // No equal-split, no remembered default, no client-invented mix appeared anywhere.
  await expect(page.getByTestId("composer-mix-inputs"), "no fabricated mix is offered").toHaveCount(0);

  const runs = await gwRead(page, "/gw/rounds");
  expect((runs.b as unknown as unknown[]).length, "a blocked recommendation persisted nothing").toBe(0);
});

test("MIX-01 the side-effect-free preview shows the governed mix, rationale and provenance and persists NOTHING", async ({ request, page }) => {
  const names = await governedSetupRunMixPolicy(request);      // GOVERNED SETUP (ruling D)

  await page.goto(`${WB_URL}/`);
  await page.getByTestId("new-run").click();
  // DISCRIMINATING persistence baseline, taken after OPENING and EDITING the composer (Codex point 4).
  await page.getByTestId("composer-posts").fill("2");
  const afterEdit = await durableState(page);
  expect(afterEdit.runIds, "opening/editing the composer creates no run").toEqual([]);

  await page.getByTestId("composer-recommend").click();

  const inputs = page.getByTestId("composer-mix-inputs");
  await expect(inputs, "the governed mix renders").toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("composer-mix"), "the composer reports a recommended state")
    .toHaveAttribute("data-state", "recommended");

  // NON-ZERO and EXACT: the counts sum to the expected slots, and at least one is positive. An
  // all-zero or blank allocation is exactly what #376 exists to eliminate.
  const counts = await page.locator('[data-testid^="composer-mix-"][data-recommended]').evaluateAll(
    (els) => els.map((e) => Number((e as HTMLElement).dataset.recommended)));
  expect(counts.length, "one input per eligible framework").toBe(names.length);
  expect(counts.reduce((a, b) => a + b, 0), "the recommendation fills every expected slot").toBe(14);
  expect(Math.max(...counts), "the recommendation is NOT all-zero").toBeGreaterThan(0);

  // Rationale + the deterministic posture, stated rather than implied.
  await expect(page.getByTestId("composer-rationale-statement")).toContainText("No model was called");
  await expect(page.getByTestId("composer-rationale-algorithm")).toContainText("largest_remainder_v1");
  await expect(page.getByTestId("composer-rationale-model-posture")).toContainText("not_applicable");

  // Generation provenance is visible BEFORE the operator touches the mix — but the proposal id is NOT,
  // because no proposal exists yet: the preview is side-effect-free and the fence is minted on submit.
  const prov = page.getByTestId("composer-provenance");
  await expect(prov).toBeVisible();
  expect(await prov.getAttribute("data-proposal-id"), "no proposal id exists at preview time").toBeNull();
  expect(Number(await prov.getAttribute("data-policy-generation")), "the policy generation is shown").toBeGreaterThan(0);

  // THE DISCRIMINATING ASSERTION (Codex P1): after the recommendation PREVIEW, still nothing durable —
  // no run, no slots. (The proposal-row and audit/history discrimination is proven with real DB reads
  // in gates/run_mix_selftest.py §4a on the same candidate; the browser boundary cannot list proposals
  // or read audit, by design.) A regression that re-persisted a proposal on preview would still leave
  // rounds empty, so this row is paired with that backend proof, not a substitute for it.
  const runs = await gwRead(page, "/gw/rounds");
  expect((runs.b as unknown as unknown[]).length, "the preview creates no run").toBe(0);
});

test("MIX-04 policy drift between preview and submit fails closed — no run, no proposal", async ({ request, page }) => {
  // Precondition: MIX-01's policy generation is current and a preview is on screen.
  await page.goto(`${WB_URL}/`);
  await page.getByTestId("new-run").click();
  await page.getByTestId("composer-posts").fill("2");
  await page.getByTestId("composer-recommend").click();
  await expect(page.getByTestId("composer-mix-inputs")).toBeVisible({ timeout: 30_000 });

  const before = await durableState(page);

  // GOVERNED SETUP — supersede the recommendation policy AFTER the operator previewed, through the
  // authority's own path. The composer still holds the previous preview's fingerprint.
  await governedSetupRunMixPolicy(request);

  await page.getByTestId("composer-submit").click();

  // FAIL CLOSED: a typed stale state, submit disabled, draft preserved, and NOTHING created.
  await expect(page.getByTestId("composer-mix-stale"), "the stale drift is surfaced as its own state")
    .toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("composer-submit"), "planning is disabled until a fresh preview").toBeDisabled();
  await expect(page, "a stale submit does not navigate to a created run").toHaveURL(/\/$|\/\?/);
  const after = await durableState(page);
  expect(after.runIds, "fail closed: the stale submit created no run").toEqual(before.runIds);
});

test("MIX-02 an amended mix is planner-validated and snapshotted immutably with the run", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await page.getByTestId("new-run").click();
  await page.getByTestId("composer-posts").fill("2");
  await page.getByTestId("composer-label").fill("376-mix02");
  await page.getByTestId("composer-recommend").click();
  await expect(page.getByTestId("composer-mix-inputs")).toBeVisible({ timeout: 30_000 });

  // AMEND: move one slot between two frameworks, keeping the planner's exact total. The recommended
  // values are read from the DOM so the amendment is relative to what was actually recommended.
  const boxes = page.locator('[data-testid^="composer-mix-"][data-recommended]');
  const n = await boxes.count();
  const recommended = await boxes.evaluateAll((els) => els.map((e) => Number((e as HTMLElement).dataset.recommended)));
  let amended = false;
  if (n >= 2) {
    const donor = recommended.findIndex((v) => v > 0);
    const receiver = recommended.findIndex((_, i) => i !== donor);
    await boxes.nth(donor).fill(String(recommended[donor] - 1));
    await boxes.nth(receiver).fill(String(recommended[receiver] + 1));
    amended = true;
    await expect(page.getByTestId("composer-mix-amended"), "the amendment is disclosed").toBeVisible();
  }

  await page.getByTestId("composer-submit").click();
  await page.waitForURL(/\/runs\/.+/, { timeout: 60_000 });
  const rid = (page.url().match(/\/runs\/([^?]+)/) || [])[1];
  expect(rid, "the canonical run id is in the URL").toBeTruthy();

  // INDEPENDENT persistence + provenance evidence, after a reload.
  await page.reload();
  const run = await gwRead(page, `/gw/rounds/${rid}`);
  expect(run.s).toBe(200);
  expect(((run.b.slots || []) as unknown[]).length, "the planner created the expected slots").toBe(14);

  const snap = await gwRead(page, `/gw/rounds/${rid}/recommendation-snapshot`);
  expect(snap.s, "the immutable recommendation snapshot is readable").toBe(200);
  expect(snap.b.status, "the run carries a recorded recommendation, not `unknown`").toBe("recorded");
  expect(snap.b.recommended_mix, "the ORIGINAL recommendation is preserved").toBeTruthy();
  expect(snap.b.submitted_mix, "the SUBMITTED mix is preserved").toBeTruthy();
  if (amended) expect(snap.b.mix_amended, "the amendment is recorded as such").toBe(true);
  expect(snap.b.policy_generation, "the policy generation in force is pinned").toBeTruthy();
  expect(snap.b.rationale, "the rationale shown to the operator is pinned").toBeTruthy();
});

// ------------------------------------------------------------------ presentation
test("RNG-01 the created run opens focused on its own accepted inclusive range", async ({ request, page }) => {
  // Reuse the run MIX-02 created — RNG-01 is about how creation NAVIGATES, so it must observe a run
  // that was created through the composer.
  const runs = await (await request.get(`${API}/rounds`)).json();
  const target = (runs as { round_id: string; label?: string }[]).find((r) => (r.label || "").includes("376-mix02"));
  expect(target, "MIX-02's run exists").toBeTruthy();
  const rid = target!.round_id;

  const detail = await (await request.get(`${API}/rounds/${rid}`)).json();
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review&focus=range`);
  const ws = page.getByTestId("run-schedule-workspace");
  await expect(ws).toBeVisible({ timeout: 90_000 });
  await expect(ws, "the workspace opens on the run's own span, not a default window")
    .toHaveAttribute("data-view", "range");
  // The focused window is the SERVER's accepted placement — never the client's proposal.
  expect(await ws.getAttribute("data-range-start")).toBe(detail.starts_on);
});

test("VIEW-01 Calendar, Grid and List are projections of ONE authoritative slot collection", async ({ request, page }) => {
  const runs = await (await request.get(`${API}/rounds`)).json();
  const target = (runs as { round_id: string; label?: string }[]).find((r) => (r.label || "").includes("376-mix02"));
  const rid = target!.round_id;
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review`);
  // #382 — the lens SELECTOR moved to the shell's top lens menu (the single navigation authority); the
  // projection PANELS stay in the workspace, so the parity assertion below is unchanged. Locator-only.
  await expect(page.getByTestId("lens-menu")).toBeVisible({ timeout: 90_000 });

  const orderOf = async (testid: string) =>
    await page.getByTestId(testid).getAttribute("data-slot-order");

  await page.getByTestId("lens-calendar").click();
  const calOrder = await orderOf("run-lens-calendar-panel");
  expect(calOrder, "the calendar lens projects slots").toBeTruthy();

  await page.getByTestId("lens-grid").click();
  await expect(page.getByTestId("run-lens-grid-panel")).toBeVisible();
  const gridOrder = await orderOf("run-lens-grid-panel");

  await page.getByTestId("lens-list").click();
  await expect(page.getByTestId("schedule-cells")).toBeVisible();
  const listOrder = await orderOf("schedule-cells");

  // IDENTICAL ids in IDENTICAL order — a divergent fetch or an independent sort is detectable, not
  // merely unlikely. Comparing counts alone would pass a lens that re-sorted.
  expect(gridOrder, "grid renders the same slots in the same order as the calendar").toBe(calOrder);
  expect(listOrder, "list renders the same slots in the same order as the calendar").toBe(calOrder);

  // Context (an applied filter) survives a lens switch and narrows every lens identically.
  const firstStatus = await page.locator('[data-testid^="cell-status-"]').first().innerText();
  await page.getByTestId("schedule-status").selectOption(firstStatus.trim());
  const filteredList = await orderOf("schedule-cells");
  await page.getByTestId("lens-grid").click();
  await expect(page.getByTestId("run-lens-grid-panel")).toBeVisible();
  expect(await orderOf("run-lens-grid-panel"), "the filter is preserved across the switch").toBe(filteredList);
});

// ------------------------------------------------------------------ governed stage truth
test("STG-01 stages the governed generation disables are ABSENT from the rail", async ({ page }) => {
  const runsRes = await page.request.get(`${API}/rounds`);
  const rid = ((await runsRes.json()) as { round_id: string }[])[0].round_id;
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review`);
  await expect(page.getByTestId("stage-rail")).toBeVisible({ timeout: 90_000 });

  // The rail renders no sign-off stage at all — not "rendered and disabled".
  await expect(page.getByTestId("stage-native_review"), "Language sign-off is absent").toHaveCount(0);
  await expect(page.getByTestId("stage-scholar_review"), "Religious sign-off is absent").toHaveCount(0);

  // WHY it is absent, proven from the governed artifact itself: the FULL contract still DECLARES both
  // stages with enabled=false, and the canonical projection omits exactly those. Absence therefore
  // means "the generation disabled it" — not "it was never declared", and not "a client filtered it".
  const full = await gwRead(page, "/gw/workflow-stages/active");
  const declared = ((full.b.stages || []) as { stage_key: string; enabled: boolean }[]);
  const native = declared.find((s) => s.stage_key === "native_review");
  const scholar = declared.find((s) => s.stage_key === "scholar_review");
  expect(native, "the generation still DECLARES native_review").toBeTruthy();
  expect(native!.enabled, "…with enabled=false").toBe(false);
  expect(scholar!.enabled, "…and scholar_review disabled too").toBe(false);

  const proj = await gwRead(page, "/gw/workflow-stages/active-enabled");
  const projected = ((proj.b.stages || []) as { stage_key: string }[]).map((s) => s.stage_key);
  expect(projected, "the projection omits the disabled stages").not.toContain("native_review");
  expect(projected, "the projection omits the disabled stages").not.toContain("scholar_review");
  expect(Number(proj.b.disabled_stage_count), "the projection discloses how many it excluded").toBeGreaterThanOrEqual(2);
});

test("STG-02 production-readiness terminology comes from the governed generation, verbatim", async ({ page }) => {
  const runsRes = await page.request.get(`${API}/rounds`);
  const rid = ((await runsRes.json()) as { round_id: string }[])[0].round_id;
  await page.goto(`${WB_URL}/runs/${rid}?stage=schedule_review`);
  await expect(page.getByTestId("stage-rail")).toBeVisible({ timeout: 90_000 });

  const proj = await gwRead(page, "/gw/workflow-stages/active-enabled");
  const final = ((proj.b.stages || []) as { stage_key: string; stage_label: string }[])
    .find((s) => s.stage_key === "final_review");
  expect(final, "the generation declares the final_review stage").toBeTruthy();
  expect(final!.stage_label, "ruling B — ONE governed label").toBe("Approved for production");

  // Rendered VERBATIM from the artifact, and the superseded wording appears nowhere on the surface.
  await expect(page.getByTestId("stage-final_review")).toContainText("Approved for production");
  await expect(page.getByText("Publish approval"), "the old label is gone from the rendered rail").toHaveCount(0);
});
