import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";
import { resolveAllowedPath, resolveAllowedWritePath } from "../lib/api-contract";

// #357 — the governed Script generation control.
//
// WHAT THESE GUARD. #355 shipped Scripts read-first because the canonical route carried no principal
// authorization on this seam; #357 closed that gap and the control is now offered. Three things could
// silently regress, and each would look correct on screen:
//   1. V2 could start deciding availability itself. The whole contract is that the SERVER decides —
//      a surface that re-derived eligibility could disagree with the authority governing the command.
//   2. A typed denial could be flattened into a generic "unavailable", destroying the distinction
//      between "you are not an approver", "the inputs moved", and "nothing to generate".
//   3. The control could be offered while an attempt is already running — the duplicate-run hazard the
//      durable job exists to remove.
//
// The boundary assertions run in-process against the pure functions: admission is decidable without
// issuing a request, and asserting it that way keeps the suite free of side effects it never needed.

const ROUND = "RGEN357";

function decision(over: Record<string, unknown> = {}) {
  return {
    action: "script_generate", round_id: ROUND, stage: "script_review",
    available: false, reason_code: null, detail: null,
    attempt_id: null, job_status: null, manifest_digest: null,
    manifest_version: "script-manifest/v1",
    input_revisions: [{ slot_id: "S1", topic_id: "t1", topic_revision: 1 }],
    source_gate_id: "gate-1", source_decision_generation: "gen-1",
    workflow_version_id: "wf-1", subject_principal: null,
    capability_binding: "not_applicable", requires_confirmation: true, retry_safe: false,
    ...over,
  };
}

async function withDecision(page: import("@playwright/test").Page, body: unknown) {
  await page.route("**/gw/workflow-stages/active-enabled", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({
      version_id: "wfv-357", version_no: 3, status: "active",
      stages: [{ stage_key: "script_review", stage_label: "Scripts", stage_group: "Content", ordinal: 1,
                 enabled: true, gate_stage: "script_review", stage_kind: "transition",
                 generator_kind: "ai", writer_mode: "scripts", generates_from: "TOPIC_APPROVED",
                 approve_to: null }],
    }),
  }));
  await page.route(`**/gw/rounds/${ROUND}`, (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ round_id: ROUND, label: "g357", slots: [{ slot_id: "S1", status: "TOPIC_APPROVED" }] }),
  }));
  await page.route("**/stages/script_review/action", (r) => r.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(body),
  }));
  await page.route("**/stages/script_review/state", (r) => r.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ stage: "script_review" }),
  }));
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
}

test("an AVAILABLE decision offers the governed control with its attempt identity (#357)", async ({ page }) => {
  await withDecision(page, decision({ available: true, manifest_digest: "f3c29a18f8b7aaaa" }));
  const gen = page.getByTestId("scripts-generation");
  await expect(gen).toHaveAttribute("data-available", "true");
  await expect(page.getByTestId("scripts-generate")).toBeEnabled();
  // The pinned inputs and manifest are surfaced, so a human can see WHAT the attempt is bound to.
  await expect(page.getByTestId("scripts-manifest-digest")).toHaveText("f3c29a18f8b7aaaa");
  await expect(page.getByTestId("scripts-pinned-count")).toHaveText("1");
});

test("each typed denial is rendered DISTINCTLY, never a generic unavailable (#357)", async ({ page }) => {
  // The distinction is the product: flattening these to one string would leave an operator unable to
  // tell an authority problem from a state problem from an empty queue.
  for (const code of ["principal_missing", "principal_not_approver", "no_eligible_input",
                      "mixed_topic_decision_generations", "attempt_in_progress"]) {
    await withDecision(page, decision({ available: false, reason_code: code, detail: `d:${code}` }));
    const gen = page.getByTestId("scripts-generation");
    await expect(gen, code).toHaveAttribute("data-reason-code", code);
    await expect(gen, code).toHaveAttribute("data-available", "false");
    await expect(page.getByTestId("scripts-generation-state"), code).toHaveText(code);
    // No control is offered for any denial — not a disabled one, not a hidden one.
    await expect(page.getByTestId("scripts-generate"), code).toHaveCount(0);
  }
});

test("an ACTIVE attempt suppresses the control and shows the durable attempt (#357)", async ({ page }) => {
  // The duplicate-run guard: while an attempt is live the control must not be offered, and the
  // durable job identity must be visible so the operator can see WHY.
  await withDecision(page, decision({
    available: false, reason_code: "attempt_in_progress", job_status: "running",
    attempt_id: "44f2ee5c-0000-0000-0000-000000000000", detail: "A governed Script attempt is already in progress.",
  }));
  await expect(page.getByTestId("scripts-generate")).toHaveCount(0);
  await expect(page.getByTestId("scripts-attempt-id")).toContainText("44f2ee5c");
  await expect(page.getByTestId("scripts-job-status")).toHaveText("running");
});

test("V2 recomputes NOTHING — an implausible server answer is still projected verbatim (#357)", async ({ page }) => {
  // Deliberately contradictory: zero pinned inputs yet available=true. A surface that re-derived
  // eligibility would "helpfully" hide the control and diverge from the authority that governs it.
  await withDecision(page, decision({ available: true, input_revisions: [], manifest_digest: "deadbeefdeadbeef" }));
  await expect(page.getByTestId("scripts-generate")).toBeEnabled();
  await expect(page.getByTestId("scripts-pinned-count")).toHaveText("0");
});

test("an unreadable decision is reported as unavailable, never assumed available (#357)", async ({ page }) => {
  await page.route("**/gw/workflow-stages/active-enabled", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ version_id: "wfv-357", version_no: 3, status: "active",
      stages: [{ stage_key: "script_review", stage_label: "Scripts", stage_group: "Content", ordinal: 1,
                 enabled: true, gate_stage: "script_review", stage_kind: "transition",
                 generator_kind: "ai", writer_mode: "scripts", generates_from: "TOPIC_APPROVED", approve_to: null }] }),
  }));
  await page.route(`**/gw/rounds/${ROUND}`, (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ round_id: ROUND, slots: [{ slot_id: "S1", status: "TOPIC_APPROVED" }] }),
  }));
  await page.route("**/stages/script_review/action", (r) =>
    r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "upstream down" }) }));
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await expect(page.getByTestId("scripts-generation-error")).toBeVisible();
  await expect(page.getByTestId("scripts-generate")).toHaveCount(0);
});

test("the #357 boundary entries are exactly as wide as the slice (#357)", () => {
  // Added: the typed decision READ and the canonical generation WRITE.
  expect(resolveAllowedPath(["rounds", ROUND, "stages", "script_review", "action"])).not.toBeNull();
  expect(resolveAllowedWritePath(["rounds", ROUND, "stages", "script_review", "generate"])).not.toBeNull();
  // NOT widened to other stages or verbs — a governed decision belongs to the slice that needs it.
  expect(resolveAllowedWritePath(["rounds", ROUND, "stages", "production_review", "generate"])).toBeNull();
  expect(resolveAllowedPath(["rounds", ROUND, "stages", "production_review", "action"])).toBeNull();
  expect(resolveAllowedWritePath(["rounds", ROUND, "stages", "script_review", "retry"])).toBeNull();
  // The seeding workflow endpoint stays out of reach (#355 P1.2).
  expect(resolveAllowedPath(["workflow-versions", "active"])).toBeNull();
});

// ---------------------------------------------------------------------------
// #357 §6 — responsive, RTL, keyboard and accessible-name evidence for the governed control.
//
// A governed action is only usable if it is reachable. These assert the properties that break
// silently: a control that overflows its viewport, disappears under RTL, cannot be reached by
// keyboard, or presents no accessible name is not "available" in any meaningful sense, however
// truthfully the server described it.

const VIEWPORTS = [
  { name: "mobile", width: 375, height: 720 },
  { name: "tablet", width: 768, height: 900 },
  { name: "desktop", width: 1280, height: 900 },
] as const;

for (const vp of VIEWPORTS) {
  test(`the governed control is usable and does not overflow at ${vp.name} ${vp.width}px (#357)`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await withDecision(page, decision({ available: true, manifest_digest: "f3c29a18f8b7aaaa" }));

    const btn = page.getByTestId("scripts-generate");
    await expect(btn).toBeVisible();
    // The accessible name is what a screen-reader user actually hears; assert it, not the markup.
    await expect(btn).toHaveAccessibleName(/generate scripts/i);

    // The page must not scroll horizontally — the 375px failure mode this repo has been bitten by.
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow at ${vp.width}px`).toBeLessThanOrEqual(0);

    // And the control itself must sit inside the viewport, not merely exist in the DOM.
    const box = await btn.boundingBox();
    expect(box, "control has a layout box").not.toBeNull();
    expect(box!.x, "control starts inside the viewport").toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width, "control ends inside the viewport").toBeLessThanOrEqual(vp.width + 1);
  });
}

test("the governed control survives RTL without losing its accessible name (#357)", async ({ page }) => {
  await withDecision(page, decision({ available: true }));
  await page.evaluate(() => document.documentElement.setAttribute("dir", "rtl"));
  const btn = page.getByTestId("scripts-generate");
  await expect(btn).toBeVisible();
  await expect(btn).toHaveAccessibleName(/generate scripts/i);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "RTL must not introduce horizontal overflow").toBeLessThanOrEqual(0);
});

test("the governed control is keyboard reachable and operable (#357)", async ({ page }) => {
  await withDecision(page, decision({ available: true }));
  const btn = page.getByTestId("scripts-generate");
  await expect(btn).toBeVisible();

  // Reachable by focus (not merely clickable), and Enter must activate it — a governed action that
  // requires a mouse excludes the keyboard-only operator from the authority path entirely.
  await btn.focus();
  await expect(btn).toBeFocused();

  let posted = false;
  await page.route("**/stages/script_review/generate", (r) => {
    posted = true;
    return r.fulfill({ status: 403, contentType: "application/json",
                       body: JSON.stringify({ detail: "not authorized: principal_not_approver" }) });
  });
  await page.keyboard.press("Enter");
  await expect.poll(() => posted, { timeout: 5000 }).toBe(true);

  // The server's typed refusal is relayed verbatim, not restated as a friendlier local guess.
  await expect(page.getByTestId("scripts-generation-refusal")).toContainText(/principal_not_approver/);
});

test("a denial state carries a truthful accessible label too (#357)", async ({ page }) => {
  // The denial must be perceivable, not just visually styled — otherwise a non-sighted operator sees
  // an action that simply is not there, with no reason given.
  await withDecision(page, decision({
    available: false, reason_code: "principal_not_approver",
    detail: "Not authorized to start Script generation for this run.",
  }));
  await expect(page.getByTestId("scripts-generation-state")).toHaveText("principal_not_approver");
  await expect(page.getByTestId("scripts-generation-detail")).toContainText(/not authorized/i);
  await expect(page.getByTestId("scripts-generate")).toHaveCount(0);
});
