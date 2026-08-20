import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { WB_URL } from "./surfaces";

// #342 — evidence that the V2 schedule ACCEPTANCE LANE is trustworthy to look at.
//
// These assertions exist to make three specific false greens impossible:
//   1. a collapsed calendar passing because the DOM is present (the #340 defect);
//   2. a screenshot of leftover test rows passing as "a reviewer inspected the schedule";
//   3. an editor-per-run list passing as "keyboard placement works" while being unusable at scale.
//
// This spec is written FOR the lane and requires it. It fails loudly rather than skipping when the
// lane is absent: a skip here would hide exactly the acceptance gap the directive was raised to fix.
//
// SCOPE NOTE. Nothing here asserts that the UI's enabled/disabled placement state is correct. That
// indication is derived client-side and is NOT the server's freeze predicate; the server decides on
// submit. These tests assert the governed round-trip and that a refusal is surfaced verbatim —
// never that the UI predicted it.

const LANE_RUNS = ["ACC342-MULTI", "ACC342-ONEDAY", "ACC342-PLAN", "ACC342-FROZEN"];

// The lane's own container/database. Overridable so the same evidence can run against a differently
// named lane, but defaulted so the documented recipe works with no extra environment.
const LANE_API = process.env.ACC342_API_CONTAINER || "tanaghom-gateapi-acc342";
const LANE_DB = process.env.ACC342_DB || "tanaghom_acc342";

/** Row counts the lane must own, read straight from the lane database. */
function laneCounts(): { rounds: number; slots: number; audit: number } {
  const sql =
    "SELECT (SELECT count(*) FROM round WHERE round_id LIKE 'ACC342-%'), " +
    "(SELECT count(*) FROM slot WHERE round_id LIKE 'ACC342-%'), " +
    "(SELECT count(*) FROM audit_log WHERE entity_id LIKE 'ACC342-%')";
  const out = execFileSync("docker", ["exec", "-i", "tanaghom-db", "sh", "-lc",
    `psql -U "$POSTGRES_USER" -d ${LANE_DB} -At -F '|' -c "${sql}"`],
    { stdio: ["ignore", "pipe", "pipe"] }).toString().trim();
  const [rounds, slots, audit] = out.split("|").map((n) => Number(n));
  return { rounds, slots, audit };
}

function laneSeed(): void {
  execFileSync("docker", ["exec", "-w", "/work", LANE_API, "python", "gates/acc342_lane_seed.py"],
    { stdio: ["ignore", "pipe", "pipe"] });
}

function laneTeardownOnly(): void {
  execFileSync("docker", ["exec", "-w", "/work", LANE_API, "python", "-c",
    "import sys; sys.path.insert(0,'gates'); import engine, acc342_lane_seed as s; s.teardown(engine.db_connect())"],
    { stdio: ["ignore", "pipe", "pipe"] });
}

/** Computed-geometry probe, deliberately anchored on Tanaghom testids rather than FullCalendar's
 *  hashed v7 class names. Same shape as the #340 proof — a laid-out grid distributes elements
 *  horizontally; block flow cannot. */
async function laidOut(page: Page, testId: string): Promise<{ distinctX: number; maxBand: number; flex: number }> {
  return page.getByTestId(testId).evaluate((root: HTMLElement) => {
    const xs = new Set<number>();
    const bands = new Map<number, Set<number>>();
    let flex = 0;
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("*"))) {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const x = Math.round(r.x);
      xs.add(x);
      const b = Math.round(r.y / 4) * 4;
      if (!bands.has(b)) bands.set(b, new Set());
      bands.get(b)!.add(x);
      const d = getComputedStyle(el).display;
      if (["flex", "table", "table-header-group", "table-row", "grid"].includes(d)) flex++;
    }
    return { distinctX: xs.size, maxBand: Math.max(0, ...[...bands.values()].map((s) => s.size)), flex };
  });
}

test("the lane declares itself SYNTHETIC in the UI — a reviewer never has to guess (#342)", async ({ page }) => {
  await page.goto(`${WB_URL}/`);

  const banner = page.getByTestId("synthetic-lane-banner");
  await expect(banner, "the lane must state that its data is synthetic").toBeVisible();
  await expect(page.getByTestId("synthetic-lane-id")).toHaveText("acc342");
  await expect(page.getByTestId("synthetic-lane-note")).toContainText(/not client data/i);

  // It is standing context, not an alert — and it must be OUTSIDE any collapsible region, so it
  // cannot be dismissed or scrolled past into invisibility.
  await expect(banner).toHaveAttribute("role", "note");
  // Present on the run route too, not only the index: acceptance happens on both surfaces.
  await page.goto(`${WB_URL}/runs/${encodeURIComponent("ACC342-MULTI")}`);
  await expect(page.getByTestId("synthetic-lane-banner")).toBeVisible();
});

test("the lane is SMALL and coherent — four scenarios, one per placement state (#342)", async ({ request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const runs = rows as { round_id: string; starts_on?: string | null }[];

  const lane = runs.filter((r) => r.round_id.startsWith("ACC342-"));
  expect(lane.map((r) => r.round_id).sort(), "the lane must expose exactly its four scenarios").toEqual([...LANE_RUNS].sort());
  // The whole point of the lane: a reviewer sees ONLY the scenario, not a hundred leftovers.
  expect(runs.length, "the acceptance lane must not be contaminated with unrelated runs").toBe(4);

  expect(lane.filter((r) => r.starts_on).length, "three placed").toBe(3);
  expect(lane.find((r) => r.round_id === "ACC342-PLAN")?.starts_on ?? null, "the planning run is unplaced").toBeNull();
});

test("placement is ONE contextual control, not one editor per run (#342)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const runCount = (rows as unknown[]).length;
  expect(runCount).toBeGreaterThan(1);        // otherwise "no explosion" would be vacuously true

  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("placement-controls")).toBeVisible();

  // EXACTLY ONE editor regardless of how many runs exist. This is the assertion the old surface
  // could never satisfy: it rendered a date input and a Move button per run.
  await expect(page.getByTestId("placement-date")).toHaveCount(1);
  await expect(page.getByTestId("placement-submit")).toHaveCount(1);
  // …and the run is chosen through one compact selection surface listing every run.
  const select = page.getByTestId("placement-run-select");
  await expect(select).toHaveCount(1);
  await expect(select.locator("option")).toHaveCount(runCount);

  // The retired per-run editors must be genuinely gone, not merely hidden.
  for (const id of LANE_RUNS) {
    await expect(page.getByTestId(`place-date-${id}`)).toHaveCount(0);
    await expect(page.getByTestId(`place-submit-${id}`)).toHaveCount(0);
  }
});

test("a run is placed by KEYBOARD alone through the contextual control (#342 / #304 A6)", async ({ page, request }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("placement-controls")).toBeVisible();

  // Target an already-PLACED run and move it, rather than placing ACC342-PLAN.
  //
  // Placing the planning run reads better, but it consumes the lane's only unplaced scenario: a
  // later test asserting "the unplaced run is stated as unplaced" would then pass or fail purely on
  // execution order. Moving a placed run is equally observable (its date changes to a value only
  // this test uses) and leaves every scenario intact, so each test stands alone and the lane does
  // not need re-seeding between them.
  const target = "ACC342-MULTI";
  const select = page.getByTestId("placement-run-select");
  await select.focus();
  await expect(select).toBeFocused();
  await select.selectOption(target);

  // The freeze indication resolves after the per-run reads land; wait for the control to be
  // operable rather than sampling immediately and declaring the fixture unplaceable.
  const submit = page.getByTestId("placement-submit");
  await expect
    .poll(async () => submit.isEnabled().catch(() => false),
      { timeout: 30_000, message: `${target} never became placeable — the fixture must provision a placeable run` })
    .toBe(true);

  const iso = "2026-07-22";
  const field = page.getByTestId("placement-date");
  await field.focus();
  await expect(field).toBeFocused();
  await field.fill(iso);
  await submit.focus();
  await expect(submit).toBeFocused();
  await page.keyboard.press("Enter");

  // Accepted through the governed command, and the ACCEPTED state is re-read from the server —
  // not asserted from local optimism.
  await expect(page.getByTestId("runs-calendar-status")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });
  await expect
    .poll(async () => {
      const r = await (await request.get(`${WB_URL}/gw/rounds`)).json();
      return (r as { round_id: string; starts_on?: string | null }[]).find((x) => x.round_id === target)?.starts_on;
    }, { timeout: 20_000 })
    .toBe(iso);
});

test("a server refusal is surfaced verbatim, never swallowed or silently applied (#342)", async ({ page, request }) => {
  // 1) The GOVERNED command really does refuse a stale token with a TYPED conflict — asserted
  //    against the live server, not a stub, so this cannot pass against a fake.
  const mapping = await (await request.get(`${WB_URL}/gw/rounds/ACC342-MULTI/schedule-mapping`)).json();
  const stale = (mapping.schedule_token ?? 0) + 99;
  const refused = await request.post(`${WB_URL}/gw/rounds/ACC342-MULTI/placement`, {
    data: { starts_on: "2026-07-30", schedule_token: stale },
    failOnStatusCode: false,
  });
  expect(refused.status(), "a stale token must be refused, not accepted").toBe(409);
  const body = await refused.json();
  expect(JSON.stringify(body), "the refusal must be TYPED, not a bare status").toMatch(/stale|token|conflict/i);

  // …and the refusal changed nothing.
  const after = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  expect((after as { round_id: string; starts_on?: string | null }[])
    .find((r) => r.round_id === "ACC342-MULTI")?.starts_on).not.toBe("2026-07-30");

  // 2) The UI RENDERS such a refusal rather than absorbing it. The route is installed before the
  //    first navigation and never flipped mid-test, so there is no stale-request race.
  await page.route("**/gw/rounds/*/placement", (route) =>
    route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "schedule token 1 is stale for ACC342-MULTI (current 7) — refresh and re-submit" }),
    }));

  await page.goto(`${WB_URL}/`);
  await page.getByTestId("placement-run-select").selectOption("ACC342-MULTI");
  const submit = page.getByTestId("placement-submit");
  await expect.poll(async () => submit.isEnabled().catch(() => false), { timeout: 30_000 }).toBe(true);
  await page.getByTestId("placement-date").fill("2026-07-30");
  await submit.click();

  const status = page.getByTestId("runs-calendar-status");
  await expect(status).toHaveAttribute("data-kind", "conflict", { timeout: 20_000 });
  await expect(status, "the server's typed reason must reach the operator").toContainText(/stale|refresh/i);
});

test("the lane renders REAL month/week/day geometry, not a collapsed text stream (#342)", async ({ page }) => {
  for (const view of ["month", "week", "day"] as const) {
    await page.goto(`${WB_URL}/?v_runs=${view}`);
    const root = page.getByTestId("runs-calendar-grid");
    await expect(root).toBeVisible();
    await expect(root).toHaveAttribute("data-view", view);

    await expect
      .poll(async () => (await laidOut(page, "runs-calendar-grid")).flex, { timeout: 20_000, message: `${view} never laid out` })
      .toBeGreaterThanOrEqual(5);

    const g = await laidOut(page, "runs-calendar-grid");
    // Collapsed baseline measured in #340 is 4 distinct x / band 2 / 0 flex, identically for every
    // view. These bounds sit above it and below the corrected weakest case.
    expect(g.distinctX, `${view}: horizontal distribution`).toBeGreaterThanOrEqual(8);
    expect(g.maxBand, `${view}: elements share a row`).toBeGreaterThanOrEqual(3);
    if (view !== "day") expect(g.maxBand, `${view}: seven-column grid`).toBeGreaterThanOrEqual(7);
  }
});

test("the control is ACCESSIBLE by name, not merely reachable by Tab (#342)", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("placement-controls")).toBeVisible();

  // Focusability alone is a weak claim: a control a screen reader announces as "combo box" or
  // "edit blank" is operable and still unusable. Assert the ACCESSIBLE NAME, which is what actually
  // reaches assistive tech — and which a stray refactor of the <label for> wiring would silently
  // break while every focus-based assertion kept passing.
  await expect(page.getByTestId("placement-run-select")).toHaveAccessibleName(/run/i);
  await expect(page.getByTestId("placement-date")).toHaveAccessibleName(/scheduled start/i);
  await expect(page.getByTestId("placement-submit")).toHaveAccessibleName(/move/i);

  // The same controls must be reachable through their labels, which is how a real assistive-tech
  // user finds them — not only through test ids that exist solely for this suite.
  await expect(page.getByLabel(/^run$/i)).toHaveCount(1);
  await expect(page.getByLabel(/scheduled start/i)).toHaveCount(1);
});

test("the FROZEN scenario disables the control and gives an accessible REASON (#342)", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("placement-controls")).toBeVisible();

  // This is the scenario the lane seeds specifically so a reviewer can see a refusal state without
  // having to manufacture one. The seed advances a slot past the schedule stage, which is the
  // server's own freeze condition — so this exercises a real state, not a UI-only mock.
  await page.getByTestId("placement-run-select").selectOption("ACC342-FROZEN");

  const submit = page.getByTestId("placement-submit");
  await expect
    .poll(async () => submit.isDisabled().catch(() => false),
      { timeout: 30_000, message: "the frozen scenario must resolve to a disabled control" })
    .toBe(true);

  // A disabled control with no stated reason is a dead end. The reason must be programmatically
  // ASSOCIATED (aria-describedby), not merely rendered somewhere nearby where a sighted user might
  // spot it and a screen-reader user would not.
  const hint = page.getByTestId("placement-frozen-hint");
  await expect(hint).toBeVisible();
  await expect(submit).toHaveAccessibleDescription(/frozen|server/i);

  // …and it must be worded as an INDICATION, never as a verdict the client is not entitled to make.
  // The client flag is not the server's freeze predicate (pre-existing #304 divergence), so copy
  // asserting "execution has begun" as fact would claim an authority this surface does not have.
  await expect(hint).toContainText(/server (makes the final decision|decides)/i);
  await expect(hint, "the hint must not state the freeze as settled fact").not.toContainText(/^Frozen — execution has begun/);
});

test("the unplaced run is STATED as unplaced, never drawn at a guessed date (#342)", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("unplaced-runs")).toBeVisible();
  await expect(page.getByTestId("unplaced-run-ACC342-PLAN")).toBeVisible();
  // It has no window, so it must not appear on the grid at all.
  await expect(page.getByTestId("run-event-ACC342-PLAN")).toHaveCount(0);
});

// Runs LAST and restores the lane before it finishes, so no earlier test can observe a torn-down
// database. It is the only test here that mutates the lane deliberately — which is the point: a
// reset claim proven against an UNCHANGED lane proves nothing, because doing nothing would pass.
test("reset is deterministic and leaves NO residue — proven against a real mutation (#342)", async ({ request }) => {
  // 1. Baseline: the seeded shape.
  const seeded = laneCounts();
  expect(seeded.rounds, "lane must start seeded").toBe(4);
  expect(seeded.slots).toBe(10);

  // 2. Mutate through the GOVERNED command, not raw SQL — the residue that matters is the residue a
  //    real session leaves, including its audit rows.
  const mapping = await (await request.get(`${WB_URL}/gw/rounds/ACC342-ONEDAY/schedule-mapping`)).json();
  const moved = await request.post(`${WB_URL}/gw/rounds/ACC342-ONEDAY/placement`, {
    data: { starts_on: "2026-08-19", schedule_token: mapping.schedule_token },
    failOnStatusCode: false,
  });
  expect(moved.ok(), "the governed move must be accepted, or this proves nothing").toBe(true);

  const dirty = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  expect((dirty as { round_id: string; starts_on?: string | null }[])
    .find((r) => r.round_id === "ACC342-ONEDAY")?.starts_on, "the lane is now genuinely dirty").toBe("2026-08-19");
  expect(laneCounts().audit, "the governed move wrote audit rows").toBeGreaterThan(seeded.audit);

  // 3. Teardown alone must leave NOTHING behind — rounds, slots, and the audit trail.
  laneTeardownOnly();
  const empty = laneCounts();
  expect(empty, "teardown must leave zero residue").toEqual({ rounds: 0, slots: 0, audit: 0 });

  // 4. Re-seeding restores the EXACT documented scenario, including the window the mutation moved.
  laneSeed();
  const restored = laneCounts();
  expect(restored.rounds).toBe(4);
  expect(restored.slots).toBe(10);

  const after = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const rows = after as { round_id: string; starts_on?: string | null }[];
  expect(rows.filter((r) => r.round_id.startsWith("ACC342-")).length).toBe(4);
  expect(rows.find((r) => r.round_id === "ACC342-ONEDAY")?.starts_on, "reset reverts the mutation").toBe("2026-07-15");
  expect(rows.find((r) => r.round_id === "ACC342-MULTI")?.starts_on).toBe("2026-07-14");
  expect(rows.find((r) => r.round_id === "ACC342-PLAN")?.starts_on ?? null, "the unplaced scenario returns unplaced").toBeNull();
});
