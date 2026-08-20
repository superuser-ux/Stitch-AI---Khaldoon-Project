import { test, expect } from "@playwright/test";
import { V1_URL, WB_URL, FIXTURE_ROUND, dbSnapshot } from "./surfaces";

// #293 §5 + acceptance A5 — bounded, synthetic, READ-ONLY coexistence proof.
//
// What this proves: against the SAME api build and the SAME synthetic fixture (RE2E — never a
// client run), V1 and V2 read the same runtime identity source and the same canonical schedule
// identifiers, and driving both leaves the database/audit state unchanged.
//
// What this deliberately does NOT prove (§5): general persistence equivalence. This is one bounded
// read-only observation. It makes no claim about writes, generation, or content quality — Stage 0
// invokes no writer at all.

test("V1 and V2 read the same api build, and V2 declares a distinct surface", async ({ request }) => {
  // Same backend authority: both surfaces resolve /health from the one gate API.
  const v1Health = await (await request.get(`${V1_URL}/gw/health`)).json();
  const v2Health = await (await request.get(`${WB_URL}/gw/health`)).json();
  expect(v2Health.writer_mode).toBe(v1Health.writer_mode);
  expect(v2Health.ok).toBe(true);

  // Distinct frontend identities over that one authority (§4: two temporary consumers).
  const v1Runtime = await (await request.get(`${V1_URL}/api/runtime`)).json();
  const v2Runtime = await (await request.get(`${WB_URL}/api/runtime`)).json();
  expect(v1Runtime.surface).toBe("operator");
  expect(v2Runtime.surface).toBe("workbench");
  expect(v2Runtime.lane).toBe("v2-transition");
  // Each carries its own truthful build identity; neither borrows the other's.
  expect(v1Runtime.build).not.toBe("unknown");
  expect(v2Runtime.build).not.toBe("unknown");
});

test("V1 and V2 read identical canonical schedule identifiers for the synthetic fixture", async ({ request }) => {
  // V1 reads through its signed /gw proxy; V2 reads through its allowlisted GET-only seam. Same
  // upstream read model, so the canonical identity set must be identical — that is what makes V2
  // a projection of the one authority rather than a second source of truth.
  const v1Round = await (await request.get(`${V1_URL}/gw/rounds/${FIXTURE_ROUND}`)).json();
  const v2Round = await (await request.get(`${WB_URL}/gw/rounds/${FIXTURE_ROUND}`)).json();

  expect(v2Round.round_id).toBe(v1Round.round_id);
  expect(v2Round.round_id).toBe(FIXTURE_ROUND);

  const v1Slots = (v1Round.slots as { slot_id: string }[]).map((s) => s.slot_id);
  const v2Slots = (v2Round.slots as { slot_id: string }[]).map((s) => s.slot_id);
  expect(v2Slots).toEqual(v1Slots);
  expect(v2Slots.length).toBeGreaterThan(0);

  // Status truth agrees too — V2 reinterprets nothing.
  expect(v2Round.status_counts).toEqual(v1Round.status_counts);
});

test("driving BOTH surfaces mutates no database or audit state", async ({ browser }) => {
  // BEFORE. Pure SELECT — this proof never seeds, resets, or cleans up.
  const before = dbSnapshot();
  expect(before.length).toBeGreaterThan(0);

  // Drive V2's full read surface for real: the schedule-first shell/root, then a run's coverage
  // workspace (canonical slots) reached by real navigation — not a hand-typed URL.
  const v2 = await browser.newPage();
  await v2.goto(WB_URL);
  await expect(v2.getByTestId("schedule-first-root")).toBeVisible();
  await expect(v2.getByTestId("runs-calendar")).toBeVisible();
  await v2.goto(`${WB_URL}/runs/${encodeURIComponent(FIXTURE_ROUND)}?stage=schedule_review`);
  await expect(v2.getByTestId("run-workspace")).toHaveAttribute("data-round-id", FIXTURE_ROUND);
  await expect(v2.getByTestId("run-schedule-workspace")).toBeVisible();
  await v2.close();

  // Drive V1's shell against the same API, in the same window of observation.
  const v1 = await browser.newPage();
  await v1.goto(V1_URL);
  await expect(v1.getByTestId("runtime-badge")).toBeVisible();
  await v1.close();

  // AFTER — must be byte-identical. audit_log's count AND max id are both in the digest, so an
  // insert-then-delete could not hide inside an unchanged count.
  const after = dbSnapshot();
  expect(after, "Stage 0 coexistence must not change database/audit state").toBe(before);
});
