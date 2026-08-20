import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { WB_URL, VIEWPORTS } from "./surfaces";

const API = process.env.API_BASE || "http://localhost:8009";

// #308 runs against an isolated DB (tanaghom_pr308) served by tanaghom-db. The shared dbSnapshot()
// reads the container's $POSTGRES_DB, which may point elsewhere, so this snapshot targets pr308
// explicitly — proving a view/range change touches THIS run's data, not some other DB's.
const SNAP_DB = process.env.PR308_DB || "tanaghom_pr308";
function snapshot(): string {
  return execFileSync("docker", ["exec", "-i", "tanaghom-db", "sh", "-lc",
    `psql -U "$POSTGRES_USER" -d "${SNAP_DB}" -At -F '|' -c "SELECT (SELECT count(*) FROM audit_log), (SELECT count(*) FROM round), (SELECT coalesce(md5(string_agg(slot_id||':'||coalesce(status::text,'')||':'||coalesce(day::text,''), ',' ORDER BY slot_id)),'none') FROM slot)"`],
    { stdio: ["ignore", "pipe", "pipe"] }).toString().trim();
}

// #308 Stage 1C — the two-level FullCalendar view system.
//
// Every assertion is about the boundary: the views PROJECT server truth, a range is presentation
// only, adaptive is deterministic from the run window (never the viewport), and view/range state is
// shareable/restorable without leaking across runs. Fixtures provision REAL runs of the exact
// durations the adaptive rule branches on — no skip hides a missing case.

const VIEWS = ["day", "week", "month", "list", "range"] as const;

/** Plan a real run of an exact duration through the governed path (so it has a pinned generation and
 *  a placed window), and return its id. Fails loudly rather than skipping. */
async function plannedRun(request: import("@playwright/test").APIRequestContext, days: number, ppd: number, startsOn: string) {
  const elig = await (await request.get(`${API}/baseline-eligibility`)).json();
  const names: string[] = (elig.eligible ?? []).map((e: { name: string }) => e.name);
  if (!names.length) throw new Error("no eligible frameworks — fixture cannot provision a run");
  const total = days * ppd;
  const mix: Record<string, number> = {};
  for (let i = 0; i < total; i++) mix[names[i % names.length]] = (mix[names[i % names.length]] ?? 0) + 1;
  const res = await request.post(`${API}/rounds`, {
    data: { days, posts_per_day: ppd, label: `308-${days}d`, format_mix: mix, starts_on: startsOn },
  });
  if (!res.ok()) throw new Error(`plan failed (${res.status()}): a real run is required, not a skip`);
  return (await res.json()).round_id as string;
}

test("runs calendar exposes all six views and switching them mutates no data (#308 A1/A4)", async ({ page, request }) => {
  const before = snapshot();
  await page.goto(`${WB_URL}/`);
  await expect(page.getByTestId("view-toolbar-runs")).toBeVisible();
  for (const v of VIEWS) {
    await expect(page.getByTestId(`view-runs-${v}`)).toBeVisible();          // keyboard-reachable button
    await page.getByTestId(`view-runs-${v}`).click();
    await expect(page.getByTestId("runs-calendar-grid")).toHaveAttribute("data-view", v);
  }
  // Custom Range inputs are present in range mode and change only the viewport.
  await page.getByTestId("view-runs-range").click();
  await expect(page.getByTestId("range-inputs-runs")).toBeVisible();
  await page.getByTestId("range-start-runs").fill("2026-09-01");
  await page.getByTestId("range-end-runs").fill("2026-09-07");
  expect(snapshot(), "switching views / setting a custom range must not touch the DB").toBe(before);
});

test("selected-run adaptive initial view is deterministic from period_len_days (#308 A2)", async ({ page, request }) => {
  const cases: { days: number; expect: string }[] = [
    { days: 1, expect: "day" },
    { days: 4, expect: "range" },   // 2..7 -> exact run-duration range
    { days: 30, expect: "month" },
  ];
  for (const c of cases) {
    const id = await plannedRun(request, c.days, 1, "2026-10-01");
    await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}`);
    // No view chosen yet -> the workspace reflects the ADAPTIVE default for this duration.
    await expect(page.getByTestId("run-schedule-workspace")).toHaveAttribute("data-view", c.expect, { timeout: 20_000 });
  }
});

test("selected-run projects canonical slots as events over the run window (#308 A3)", async ({ page, request }) => {
  const id = await plannedRun(request, 3, 2, "2026-11-02");
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  const map = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}/schedule-mapping`)).json();

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?v_${id}=month`);
  await expect(page.getByTestId("run-schedule-calendar")).toBeVisible();
  // Every canonical slot appears as an event, identified by canonical slot_id, labelled by the
  // server display_code.
  for (const p of map.positions.slice(0, 3)) {
    const ev = page.getByTestId(`cal-slot-${p.slot_id}`);
    await expect(ev).toBeVisible();
    await expect(ev).toHaveText(p.display_code);
  }
  expect(detail.slots.length).toBeGreaterThan(0);
});

test("an unplaced run shows an explicit unplaced calendar state — never a fabricated date (#308 A7)", async ({ page, request }) => {
  // A run created WITHOUT starts_on is unplaced (ruling B, #304). It must say so, not guess.
  const elig = await (await request.get(`${API}/baseline-eligibility`)).json();
  const name = (elig.eligible ?? [])[0]?.name;
  const res = await request.post(`${API}/rounds`, { data: { days: 2, posts_per_day: 1, label: "308-unplaced", format_mix: { [name]: 2 } } });
  const id = (await res.json()).round_id as string;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}`);
  await expect(page.getByTestId("run-schedule-calendar-unplaced")).toBeVisible();
  await expect(page.getByTestId("run-schedule-calendar")).toHaveCount(0);
});

test("view/range survives drill-down, back, and reload without leaking across runs (#308 A6)", async ({ page, request }) => {
  const a = await plannedRun(request, 10, 1, "2026-12-01");
  const b = await plannedRun(request, 10, 1, "2026-12-20");

  // Choose distinct views on two runs; the URL scope is per-run.
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(a)}?v_${a}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toHaveAttribute("data-view", "list");
  await page.reload();
  await expect(page.getByTestId("run-schedule-workspace")).toHaveAttribute("data-view", "list");   // restored

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(b)}?v_${b}=week`);
  await expect(page.getByTestId("run-schedule-workspace")).toHaveAttribute("data-view", "week");
  // Run A's choice did not leak into run B.
  expect(new URL(page.url()).searchParams.get(`v_${a}`), "run A's view must not appear in run B's URL").toBeNull();
});

for (const vp of VIEWPORTS) {
  for (const dir of ["ltr", "rtl"] as const) {
    test(`views have no page-level overflow at ${vp.label} ${dir} (#308 responsive)`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${WB_URL}/`);
      await page.evaluate((d) => document.documentElement.setAttribute("dir", d), dir);
      await expect(page.getByTestId("view-toolbar-runs")).toBeVisible();
      // Toolbar stays reachable (wraps, never cropped) and the page never scrolls sideways.
      for (const v of VIEWS) {
        await page.getByTestId(`view-runs-${v}`).click();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, `page overflow in ${v} at ${vp.label}/${dir}`).toBeLessThanOrEqual(0);
      }
    });
  }
}
