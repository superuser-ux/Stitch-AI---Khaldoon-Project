import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";
import { resolveAllowedPath, resolveAllowedWritePath } from "../lib/api-contract";

// #355 — the Scripts stage: a governed-derived rail, a read-first lens, and a query boundary that
// refuses rather than defaults.
//
// WHAT THESE TESTS ARE FOR. Three things could silently go wrong here, and each would look fine on
// screen:
//   1. The rail could quietly fall back to a locally invented stage list when the governed artifact
//      is unreadable — reasserting exactly the parallel mapping #355 removed.
//   2. A Scripts revisions read could lose its `artifact=script` parameter and be answered with
//      TOPIC history, rendering topic text under a Scripts heading. That is fabricated evidence, and
//      it is invisible unless something asserts the refusal.
//   3. The generation control could reappear, exposing a route that has no authorization on this
//      seam (the `_require_trusted_principal` block lives entirely inside `if mode == "topics":`).
//
// The boundary assertions run against the REAL /gw route with no mock, because the refusal is the
// property under test. The rail assertions mock the governed artifact so a specific shape can be
// forced, which is the only way to prove fail-closed behaviour without mutating a lane.

const ROUND = "RSCRIPT355";

/** A minimal, realistic active governed workflow version. */
function version(stages: Array<Partial<Record<string, unknown>>>) {
  return {
    version_id: "wfv-355",
    version_no: 7,
    status: "active",
    stages: stages.map((s, i) => ({
      stage_key: `stage_${i}`,
      stage_label: `Stage ${i}`,
      stage_group: "Content",
      ordinal: i + 1,
      enabled: true,
      gate_stage: `stage_${i}`,
      stage_kind: "transition",
      generator_kind: null,
      writer_mode: null,
      generates_from: null,
      approve_to: null,
      ...s,
    })),
  };
}

const GOVERNED = version([
  { stage_key: "schedule_review", stage_label: "Schedule", gate_stage: "schedule_review", ordinal: 1 },
  { stage_key: "topic_review", stage_label: "Topics", gate_stage: "topic_review", ordinal: 2,
    generator_kind: "ai", writer_mode: "topics", generates_from: "SCHEDULE_APPROVED" },
  { stage_key: "script_review", stage_label: "Scripts", gate_stage: "script_review", ordinal: 3,
    generator_kind: "ai", writer_mode: "scripts", generates_from: "TOPIC_APPROVED" },
  { stage_key: "production_review", stage_label: "Production", gate_stage: "production_review", ordinal: 4 },
]);

/** Serve a controlled governed artifact + a minimal round, leaving every other route real. */
async function withGoverned(page: import("@playwright/test").Page, body: unknown) {
  await page.route("**/gw/workflow-stages/active-enabled", (r) =>
    typeof body === "number"
      ? r.fulfill({ status: body, contentType: "application/json", body: JSON.stringify({ detail: "unavailable" }) })
      : r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));
  await page.route(`**/gw/rounds/${ROUND}`, (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ round_id: ROUND, label: "s355", slots: [{ slot_id: "S355-1", status: "TOPIC_APPROVED" }] }),
    }));
}

test("the stage rail is DERIVED from the active governed workflow version (#355)", async ({ page }) => {
  await withGoverned(page, GOVERNED);
  await page.goto(`${WB_URL}/runs/${ROUND}`);

  const rail = page.getByTestId("stage-rail");
  await expect(rail).toBeVisible();
  // Provenance is rendered, so a reader knows WHICH governed generation produced these stages.
  await expect(rail).toHaveAttribute("data-workflow-version", "wfv-355");
  await expect(page.getByTestId("stage-rail-provenance")).toContainText("version 7");

  // Stage keys are the canonical governed stage_key verbatim — V2 invents no vocabulary.
  await expect(page.getByTestId("stage-schedule_review")).toBeVisible();
  await expect(page.getByTestId("stage-topic_review")).toBeVisible();
  await expect(page.getByTestId("stage-script_review")).toBeVisible();
  // Labels come from the artifact, not from a local constant.
  await expect(page.getByTestId("stage-script_review")).toContainText("Scripts");
});

test("a governed stage with no built surface is visible, disabled and truthfully explained (#355)", async ({ page }) => {
  await withGoverned(page, GOVERNED);
  await page.goto(`${WB_URL}/runs/${ROUND}`);
  const production = page.getByTestId("stage-production_review");
  await expect(production).toBeVisible();          // never hidden — hiding would assert nothing exists
  await expect(production).toBeDisabled();
  await expect(production).toHaveAttribute("data-active", "false");
  await expect(production).toHaveAttribute("title", /no workbench surface is built/i);
});

// #376 — the rail now consumes the canonical ACTIVE-STAGE PROJECTION, which never returns a disabled
// stage, so this row guards the client's DEFENSIVE branch rather than the production path: if a future
// consumer or a hand-served payload ever carries `enabled:false`, the surface must still refuse to
// navigate it instead of quietly offering it. Kept deliberately — the projection is the first line, and
// this is the second.
test("a stage DISABLED in the governed version is not navigable, with the governed reason (#355)", async ({ page }) => {
  await withGoverned(page, version([
    { stage_key: "schedule_review", stage_label: "Schedule", gate_stage: "schedule_review", ordinal: 1 },
    { stage_key: "script_review", stage_label: "Scripts", gate_stage: "script_review", ordinal: 2, enabled: false },
  ]));
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  const scripts = page.getByTestId("stage-script_review");
  await expect(scripts).toBeDisabled();
  await expect(scripts).toHaveAttribute("title", /disabled in the active governed workflow version/i);
  // Fail closed: a hand-typed URL for a disabled stage must NOT render that stage's panel.
  await expect(page.getByTestId("stage-panel-script_review")).toHaveCount(0);
});

test("when the governed artifact cannot be read, NO rail is invented (#355)", async ({ page }) => {
  // The regression this guards: falling back to a local stage list would recreate the parallel
  // mapping #355 exists to delete, and would look completely normal on screen.
  await withGoverned(page, 503);
  await page.goto(`${WB_URL}/runs/${ROUND}`);
  await expect(page.getByTestId("stage-rail-unavailable")).toBeVisible();
  await expect(page.getByTestId("stage-rail")).toHaveCount(0);
  await expect(page.getByTestId("stage-panel-schedule_review")).toHaveCount(0);
  await expect(page.getByTestId("stage-panel-script_review")).toHaveCount(0);
});

test("the Scripts lens projects the SERVER's generation decision (#355 -> #357)", async ({ page }) => {
  // SUPERSEDED BY #357, deliberately. #355 asserted a hardcoded "unavailable" state, which was correct
  // then: the canonical route carried no principal authorization on this seam, so offering a control
  // would have exposed an unauthenticated write. #357 closed that gap, so the assertion now checks the
  // property that actually matters and outlives both slices — the surface PROJECTS the server's typed
  // decision and never authors its own.
  await withGoverned(page, GOVERNED);
  await page.route("**/stages/script_review/action", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ action: "script_generate", round_id: ROUND, stage: "script_review",
                           available: false, reason_code: "principal_not_approver",
                           detail: "Not authorized to start Script generation for this run.",
                           attempt_id: null, manifest_digest: null }),
  }));
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);

  await expect(page.getByTestId("scripts-workspace")).toBeVisible();
  const gen = page.getByTestId("scripts-generation");
  await expect(gen).toHaveAttribute("data-reason-code", "principal_not_approver");
  await expect(gen).toHaveAttribute("data-available", "false");
  // No control on a denial — and the reason is the server's, not a friendlier local paraphrase.
  await expect(page.getByTestId("scripts-generate")).toHaveCount(0);
  await expect(page.getByTestId("scripts-generation-detail")).toContainText(/not authorized/i);
});

// ---------------------------------------------------------------------------
// The query boundary, asserted against the REAL /gw route. No mock: refusal is the property.

test("the query boundary forwards ONLY artifact=script and refuses everything else (#355)", async ({ request }) => {
  const base = `${WB_URL}/gw/slots/S355-1/revisions`;

  // Absent artifact is REFUSED, not silently answered with the upstream `topic` default. This single
  // assertion is what makes "no topic fallback" structural rather than caller discipline.
  expect((await request.get(base)).status(), "absent artifact must be refused").toBe(403);

  // A non-script artifact is refused even though upstream would happily serve it.
  expect((await request.get(`${base}?artifact=topic`)).status(), "artifact=topic must be refused").toBe(403);

  // Duplicates are refused rather than resolved by last-wins.
  expect((await request.get(`${base}?artifact=script&artifact=topic`)).status(),
    "duplicated artifact must be refused").toBe(403);

  // Nothing arbitrary is ever forwarded.
  expect((await request.get(`${base}?artifact=script&limit=99`)).status(),
    "extra parameters must be refused").toBe(403);

  // A query on a different allowlisted path is refused — the capability is path-scoped.
  expect((await request.get(`${WB_URL}/gw/rounds?artifact=script`)).status(),
    "query on another path must be refused").toBe(403);

  // The one permitted form is NOT refused by the boundary. It may still fail upstream (no such slot
  // in this lane); what must never happen is a 403 from V2's own query boundary.
  const allowed = await request.get(`${base}?artifact=script`);
  expect(allowed.status(), "artifact=script must pass V2's query boundary").not.toBe(403);
});

test("the new read paths are inside the boundary and unrelated stages are not (#355)", async ({ request }) => {
  // `workflow-versions/active` is asserted through the PURE boundary function, deliberately NOT over
  // HTTP. Upstream's `get_workflow_version` calls `_ensure_workflow_seed`, which CREATES a baseline
  // version when none is active — so a test that proxied this read could seed whatever database it
  // happened to be pointed at. The property under test here is V2's own admission decision, and that
  // is decidable without issuing the request at all. Asserting it in-process keeps the suite free of
  // a write side effect it never needed.
  expect(resolveAllowedPath(["workflow-stages", "active"]),
    "the side-effect-free governed stage read must be inside the read boundary").not.toBeNull();
  // The SEEDING endpoint must stay OUT of the boundary: it can overwrite an operator-owned workflow
  // row's metadata as a side effect of a GET, so ordinary navigation must be unable to reach it.
  expect(resolveAllowedPath(["workflow-versions", "active"]),
    "the seeding endpoint must NOT be reachable from V2").toBeNull();
  expect(resolveAllowedPath(["workflow-versions", "some-other-id"]),
    "no workflow-versions path is admitted").toBeNull();

  // The two Scripts stage reads are side-effect free, so they are asserted over real HTTP.
  for (const p of [
    `/gw/rounds/${ROUND}/stages/script_review/state`,
    `/gw/rounds/${ROUND}/stages/script_review/advanced`,
  ]) {
    expect((await request.get(`${WB_URL}${p}`)).status(), `${p} must be inside the read boundary`).not.toBe(403);
  }

  // Refused: the boundary is exactly as wide as this slice, not "stages/*".
  for (const p of [
    `/gw/rounds/${ROUND}/stages/topic_review/state`,
    `/gw/rounds/${ROUND}/stages/production_review/state`,
  ]) {
    expect((await request.get(`${WB_URL}${p}`)).status(), `${p} must be refused`).toBe(403);
  }
});

test("the write boundary admits ONLY the canonical Script command (#355 -> #357)", async ({ request }) => {
  // SUPERSEDED BY #357. The original assertion — that V2 refuses this write entirely — was right while
  // the route was unauthenticated. #357 authorizes it on every caller, so the boundary now admits it.
  // What must NOT change is the shape of the permission: EXACTLY this one command, never a widening.
  expect(resolveAllowedWritePath(["rounds", ROUND, "stages", "script_review", "generate"]),
    "the canonical Script command is now enumerated").not.toBeNull();
  for (const p of [
    ["rounds", ROUND, "stages", "production_review", "generate"],
    ["rounds", ROUND, "stages", "script_review", "retry"],
    ["rounds", ROUND, "stages", "script_review", "approve"],
  ]) {
    expect(resolveAllowedWritePath(p), `must stay refused: ${p.join("/")}`).toBeNull();
  }

  // And the seam is still not an authority: an unsigned caller reaching upstream is refused THERE.
  const res = await request.post(`${WB_URL}/gw/rounds/${ROUND}/stages/script_review/generate`, { data: {} });
  expect([401, 403, 409, 503]).toContain(res.status());
  expect(res.status(), "an unsigned caller must never be accepted").not.toBe(200);
});
