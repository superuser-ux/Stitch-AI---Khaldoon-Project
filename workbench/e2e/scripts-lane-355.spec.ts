import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

/** The lane's gate API. Read directly (not through /gw) so upstream ground truth is established
 *  independently of the boundary under test. */
const API = process.env.API_BASE || "http://localhost:8009";

// #355 — the Scripts lens against a REAL governed lane. No mocks anywhere in this file.
//
// The sibling `scripts-stage.spec.ts` forces specific governed shapes with route mocks, which is the
// only way to prove fail-closed behaviour for divergent/ambiguous/unreadable mappings. This file is
// the complement: it proves the lens renders the ACTUAL canonical read model of a run that reached
// `TOPIC_APPROVED` through the governed chain, with nothing intercepted.
//
// LANE PREREQUISITE. It needs the #355 candidate lane: an isolated database initialised from the
// committed schema + every migration, whose run was driven `POST /rounds` -> open `schedule_review`
// -> decide(approve) -> resolve (Topic generation runs automatically on acceptance) -> open
// `topic_review` -> decide(approve) -> resolve, leaving every slot at `TOPIC_APPROVED`. See
// docs/v2-transition/scripts-lane-355.md. Pointed at a lane without such a run, these fail loudly —
// they never skip, because a skip is not a pass.

/** The run must be genuinely at TOPIC_APPROVED, or the evidence below proves nothing. */
async function topicApprovedRound(request: import("@playwright/test").APIRequestContext) {
  const res = await request.get(`${API}/rounds`);
  expect(res.ok(), `the lane API must be reachable at ${API}`).toBeTruthy();
  const rounds = (await res.json()) as Array<{ round_id: string }>;
  for (const r of rounds) {
    const d = await request.get(`${API}/rounds/${r.round_id}`);
    if (!d.ok()) continue;
    const body = (await d.json()) as { status_counts?: Record<string, number>; slots?: Array<{ slot_id: string }> };
    if ((body.status_counts?.TOPIC_APPROVED ?? 0) > 0) {
      return { roundId: r.round_id, slotId: body.slots?.[0]?.slot_id ?? "" };
    }
  }
  throw new Error(
    "no run at TOPIC_APPROVED in this lane — the #355 candidate fixture is required; " +
    "this spec fails rather than silently skipping.",
  );
}

test("the Scripts lens renders the REAL governed stage state (#355)", async ({ page, request }) => {
  const { roundId } = await topicApprovedRound(request);

  // What upstream actually says, fetched independently of the browser.
  const state = await (await request.get(`${API}/rounds/${roundId}/stages/script_review/state`)).json();
  expect(state.stage, "upstream must report the Scripts gate").toBe("script_review");

  await page.goto(`${WB_URL}/runs/${roundId}?stage=script_review`);
  await expect(page.getByTestId("scripts-workspace")).toBeVisible();

  // The rail came from the real governed artifact, not a fixture.
  await expect(page.getByTestId("stage-rail")).toBeVisible();
  await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-gate-stage", "script_review");

  // The state panel renders SERVER values. `pending_input` is the count of TOPIC_APPROVED slots
  // waiting for scripts — the governed `generates_from` contract, observed rather than described.
  const ok = page.getByTestId("scripts-state-ok");
  await expect(ok).toBeVisible();
  await expect(ok).toContainText(String(state.pending_input));
  await expect(page.getByTestId("scripts-state-error")).toHaveCount(0);
});

test("script history is EMPTY (not fabricated) for a run whose scripts never generated (#355)", async ({ page, request }) => {
  const { roundId, slotId } = await topicApprovedRound(request);
  expect(slotId, "the run must expose a canonical slot id").not.toBe("");

  // Ground truth: upstream has no script revisions for this slot.
  const upstream = await (await request.get(`${API}/slots/${slotId}/revisions?artifact=script`)).json();
  expect(Array.isArray(upstream) && upstream.length === 0,
    "this fixture must have NO script revisions — generation is not exposed").toBeTruthy();

  await page.goto(`${WB_URL}/runs/${roundId}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${slotId}`).click();

  // The truthful empty state — distinct from "unavailable" and never invented content.
  await expect(page.getByTestId(`scripts-revisions-empty-${slotId}`)).toBeVisible();
  await expect(page.getByTestId(`scripts-revisions-error-${slotId}`)).toHaveCount(0);
});

test("the Scripts lens never renders TOPIC history, though the slot HAS topics (#355)", async ({ page, request }) => {
  // This is the sharpest available proof that the query boundary matters. The same slot has real
  // topic revisions upstream; if the Scripts read ever lost `artifact=script` it would render that
  // topic text under a Scripts heading. Here the boundary refuses instead, so the surface shows the
  // empty state and none of the topic content.
  const { roundId, slotId } = await topicApprovedRound(request);

  const topics = await (await request.get(`${API}/slots/${slotId}/revisions?artifact=topic`)).json();
  expect(Array.isArray(topics) && topics.length > 0,
    "the fixture slot must genuinely have topic revisions for this contrast to mean anything").toBeTruthy();
  const topicBody = String(topics[0].body ?? "").trim();
  expect(topicBody.length, "the topic revision must carry renderable text").toBeGreaterThan(0);

  await page.goto(`${WB_URL}/runs/${roundId}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${slotId}`).click();
  await expect(page.getByTestId(`scripts-revisions-empty-${slotId}`)).toBeVisible();

  // The actual topic text must appear NOWHERE on the Scripts surface.
  await expect(page.getByTestId("scripts-workspace")).not.toContainText(topicBody);

  // And V2 refuses the un-parameterised read outright rather than answering it with topics.
  const bare = await request.get(`${WB_URL}/gw/slots/${slotId}/revisions`);
  expect(bare.status(), "an artifact-less Scripts read must be refused, never defaulted to topic").toBe(403);
});

test("generation stays unavailable on a run that satisfies its input contract (#355)", async ({ page, request }) => {
  // The strongest form of the read-first claim: this run has 28 slots at TOPIC_APPROVED, i.e. it
  // fully satisfies `generates_from` for script generation. The control is still absent, because
  // the route carries no authorization on this seam — not because there was nothing to generate.
  const { roundId } = await topicApprovedRound(request);
  const state = await (await request.get(`${API}/rounds/${roundId}/stages/script_review/state`)).json();
  expect(state.pending_input, "the fixture must satisfy the generation input contract").toBeGreaterThan(0);
  expect(state.generator, "upstream must report an AI generator for this stage").toBe("ai");

  await page.goto(`${WB_URL}/runs/${roundId}?stage=script_review`);
  await expect(page.getByTestId("scripts-generation-unavailable")).toBeVisible();
  await expect(page.getByRole("button", { name: /generate/i })).toHaveCount(0);

  const res = await request.post(`${WB_URL}/gw/rounds/${roundId}/stages/script_review/generate`, { data: {} });
  expect(res.status(), "V2 must refuse to write script generation").toBe(403);
});
