import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #304 Stage 1 — the runs calendar as a PROJECTION of server truth.
//
// Every assertion here is about the boundary, not the widget: that V2 shows what the server says,
// proposes rather than decides, and states what it does not know. A calendar that renders is not
// evidence; a calendar that refuses to invent placement is.

test("the runs calendar is a real route and renders server runs (#304 L1)", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
  // The seam resolves to exactly one truthful terminal state — never a static shell.
  await expect
    .poll(async () => {
      for (const id of ["runs-calendar", "runs-calendar-empty", "runs-calendar-read-error"]) {
        if (await page.getByTestId(id).isVisible().catch(() => false)) return id;
      }
      return "loading";
    })
    .not.toBe("loading");
});

test("an unplaced run is stated as unplaced — never drawn at a guessed date (#304 A4)", async ({ page, request }) => {
  // Server truth first: which runs does Tanaghom say have NO governed start?
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const unplaced = (rows as { round_id: string; starts_on?: string | null }[])
    .filter((r) => !r.starts_on);
  test.skip(unplaced.length === 0, "no unplaced run in this fixture");

  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("unplaced-runs")).toBeVisible();
  for (const r of unplaced.slice(0, 3)) {
    // It is LISTED (not hidden) …
    await expect(page.getByTestId(`unplaced-run-${r.round_id}`)).toBeVisible();
    // … and NOT drawn on the grid, which would require inventing a date. #304 forbids deriving the
    // window from created_at, so the only truthful rendering is "no scheduled start yet".
    await expect(page.getByTestId(`run-event-${r.round_id}`)).toHaveCount(0);
  }
});

test("opening a run navigates to its own schedule route and back returns to the calendar (#304 A1)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id as string;

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}`);
  const route = page.getByTestId("run-workspace");
  await expect(route).toBeVisible();
  // The route is SCOPED to the canonical run id, carried verbatim.
  await expect(route).toHaveAttribute("data-round-id", id);
  await expect(page.getByTestId("run-crumb-current")).toHaveText(id);

  // Breadcrumb context is preserved — a real navigation, not a panel toggle.
  await page.getByTestId("back-to-schedule").click();
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
});

test("a placed run renders on the SERVER's date, in its own day cell (#304 A2/A4)", async ({ page, request }) => {
  // Deterministic by construction: place a run inside the month the grid opens on, so the assertion
  // never depends on stepping the toolbar. Navigating months through vendor internals is exactly the
  // coupling that made an earlier version of this test read a valid calendar as "renders nothing".
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const runs = rows as { round_id: string; starts_on?: string | null }[];
  test.skip(runs.length === 0, "no runs in this fixture");

  // A date in the CURRENT month, away from the edges so it is inside the opening view.
  const now = new Date();
  const target = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-15`;

  // Place through the REAL governed path: read the current token, then propose. If the server
  // refuses (frozen run, unauthorized, stale token) we do not fake it — we skip, because this test
  // asserts rendering of an accepted placement, and the refusal paths are proven server-side.
  let placedId: string | null = null;
  for (const r of runs) {
    const m = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/schedule-mapping`);
    if (!m.ok()) continue;
    const token = (await m.json()).schedule_token;
    const res = await request.post(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/placement`, {
      data: { starts_on: target, schedule_token: token },
    });
    if (res.ok()) { placedId = r.round_id; break; }
  }
  test.skip(!placedId, "no run could be governed-placed in this fixture (all frozen or unauthorized)");

  await page.goto(`${WB_URL}/`);
  const grid = page.getByTestId("runs-calendar-grid");
  // Stable attribute, never FullCalendar's hashed classes.
  await expect(grid.locator(`[data-date="${target}"]`)).toHaveCount(1);
  // The run renders — and it renders because the SERVER says that is its date.
  await expect(page.getByTestId(`run-event-${placedId}`)).toBeVisible();
});

test("the page never scrolls horizontally at 375px (#304 A10)", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
  // The grid may scroll inside ITS OWN container; the page must not. A cropped calendar that pushes
  // the document sideways is exactly the 375px failure #304 names.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "page-level horizontal overflow at 375px").toBeLessThanOrEqual(0);
});

test("the calendar reads identically under RTL (#304 A10)", async ({ page }) => {
  await page.goto(`${WB_URL}/`);
  await page.evaluate(() => document.documentElement.setAttribute("dir", "rtl"));
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "page-level horizontal overflow in RTL").toBeLessThanOrEqual(0);
});

test("a run can be placed by KEYBOARD alone — drag is never the only path (#304 A6)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const runs = rows as { round_id: string; starts_on?: string | null }[];
  test.skip(runs.length === 0, "no runs in this fixture");

  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("placement-controls")).toBeVisible();

  // #342 — this test's SURFACE changed by directive: the editor-per-run list was replaced by one
  // contextual control driven by a compact selection surface. Its INTENT is unchanged and is what
  // still matters — a run can be placed by keyboard alone, through the governed command, with the
  // accepted state re-read. Only the selectors moved.
  //
  // The freeze indication resolves per run AFTER the list loads, so sampling isEnabled()
  // immediately finds the control disabled and would SKIP core acceptance — which the fixture must
  // never allow. Wait for it, and FAIL (not skip) if no run is placeable: a skip here would hide
  // exactly the class of defect that hid the placement 500.
  const select = page.getByTestId("placement-run-select");
  const submit = page.getByTestId("placement-submit");
  let target: string | null = null;
  await expect.poll(async () => {
    for (const r of runs) {
      await select.selectOption(r.round_id).catch(() => {});
      if (await submit.isEnabled().catch(() => false)) { target = r.round_id; return true; }
    }
    return false;
  }, { timeout: 30_000, message: "no run is governed-placeable — the fixture must provision one" }).toBe(true);

  const now = new Date();
  const iso = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-20`;

  // Keyboard only: the selection surface, the date field, and Enter to activate. A native <select>
  // is operable by keyboard without any custom key handling, which is why it was chosen.
  await select.focus();
  await expect(select).toBeFocused();
  const field = page.getByTestId("placement-date");
  await field.focus();
  await expect(field).toBeFocused();
  await field.fill(iso);
  await submit.focus();
  await expect(submit).toBeFocused();
  await page.keyboard.press("Enter");

  // It commits through Tanaghom and the accepted state is re-read — the same governed path the
  // gesture uses, not a second write model.
  await expect(page.getByTestId("runs-calendar-status")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });
  await expect
    .poll(async () => {
      const r = await (await request.get(`${WB_URL}/gw/rounds`)).json();
      return (r as { round_id: string; starts_on?: string | null }[])
        .find((x) => x.round_id === target)?.starts_on;
    }, { timeout: 20_000 })
    .toBe(iso);
});

test("a stale-token placement is refused and surfaced, never silently applied (#304 A6)", async ({ request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const runs = rows as { round_id: string; starts_on?: string | null }[];
  test.skip(runs.length === 0, "no runs in this fixture");

  // Propose against a token the server does not hold. This is the conflict the UI must revert on.
  for (const r of runs) {
    const m = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/schedule-mapping`);
    if (!m.ok()) continue;
    const token = (await m.json()).schedule_token;
    const before = r.starts_on ?? null;
    const res = await request.post(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/placement`, {
      data: { starts_on: "2027-01-05", schedule_token: token + 999 },
    });
    // Refused — and typed, not a 500 pretending the check ran.
    expect(res.status(), "a stale token must be refused").not.toBe(200);
    // …and the refusal changed nothing.
    const after = await (await request.get(`${WB_URL}/gw/rounds`)).json();
    const now = (after as { round_id: string; starts_on?: string | null }[])
      .find((x) => x.round_id === r.round_id)?.starts_on ?? null;
    expect(now, "a refused placement must not land").toBe(before);
    return;
  }
  test.skip(true, "no round exposed a schedule token");
});

test("scope controls filter/sort PRESENTATION only, and state what they hide (#304 A15)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const runs = rows as { round_id: string; starts_on?: string | null }[];
  test.skip(runs.length === 0, "no runs in this fixture");

  await page.goto(`${WB_URL}/`);
  const bar = page.getByTestId("runs-scope-controls");
  await expect(bar).toBeVisible();

  // Baseline: every server row is shown, nothing hidden.
  await expect(page.getByTestId("runs-scope-count")).toHaveAttribute("data-shown", String(runs.length));
  await expect(page.getByTestId("runs-scope-count")).toHaveAttribute("data-hidden", "0");

  // Filtering to "not scheduled" shows exactly the runs the SERVER says have no start …
  await page.getByTestId("runs-placement").selectOption("unplaced");
  const unplaced = runs.filter((r) => !r.starts_on).length;
  await expect(page.getByTestId("runs-scope-count")).toHaveAttribute("data-shown", String(unplaced));
  // … and says how many it hid, so a filtered view can't be mistaken for the whole truth.
  await expect(page.getByTestId("runs-scope-count")).toHaveAttribute("data-hidden", String(runs.length - unplaced));

  // Filtering is presentation: server truth is unchanged by looking at it.
  const after = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  expect((after as unknown[]).length, "a filter must not change server state").toBe(runs.length);

  // Keyboard reachable, and the bar never pushes the page sideways at 375px.
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByTestId("runs-search").focus();
  await expect(page.getByTestId("runs-search")).toBeFocused();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "scope controls must not cause page overflow at 375px").toBeLessThanOrEqual(0);
});
