import { test, expect, type Page } from "@playwright/test";
import { WB_URL } from "./surfaces";
import { APPEARANCE_KEY, SCHEDULE_STYLE_KEY } from "../lib/presentation-prefs";

// #340 — COMPUTED-GEOMETRY proof that FullCalendar is actually laid out, not merely present.
//
// WHY THIS EXISTS. The #337 acceptance lane shipped a calendar whose semantic DOM was correct and
// whose console was clean, but which rendered as an unstyled vertical text stream: `skeleton.css`
// was never imported, so every `.fc-*` node fell back to block flow. The suite stayed green because
// nothing in it looked at geometry — the only spatial assertions were horizontal-overflow checks,
// and a collapsed column of text has LESS horizontal overflow, not more. The broken state actively
// satisfied the tests. These assertions close exactly that gap.
//
// WHY NOT CLASS NAMES. FullCalendar v7 ships hashed, atomic class names (`.fc-Qy`, `.fc-OR`,
// `.fc-p8`) — an internal build artifact, not a public API. Asserting on them would couple this
// suite to the package's minifier. Every measurement below is therefore anchored on Tanaghom's own
// stable `data-testid` roots and reads only COMPUTED values from the descendants inside them.
//
// WHY THESE THRESHOLDS. They are measured, not guessed. With the structural CSS disabled, all ten
// surface×view combinations collapse to an identical signature — 4 distinct x-offsets, a widest row
// band of 2, 2% spread, and ZERO elements computing a positioned or flex/table formatting context.
// With it loaded, the weakest combination still reports 13 / 4 / 6% / 2 / 19. The bounds below sit
// in that gap, so each assertion fails on the collapsed render and passes on the correct one.
//
//   metric                     collapsed (all 10)   corrected (weakest)   bound used
//   distinct x-offsets                   4                  13              >= 8
//   widest row band                      2                   4              >= 3
//   positioned descendants               0                   2              >= 1
//   flex/table descendants               0                  19              >= 5
//   month+week row band                  2                  15              >= 7
//   month+week spread                   2%                 91%             >= 50%

type Geo = {
  visible: number;
  distinctX: number;
  maxBand: number;
  spreadPct: number;
  positioned: number;
  flexOrTable: number;
};

/** Read the computed layout of everything rendered inside a calendar root. Pure measurement — it
 *  asserts nothing, so the same probe backs every row of the matrix. */
async function geometry(page: Page, testId: string): Promise<Geo> {
  return page.getByTestId(testId).evaluate((root: HTMLElement) => {
    const xs = new Set<number>();
    const bands = new Map<number, Set<number>>();
    let positioned = 0;
    let flexOrTable = 0;
    let visible = 0;

    for (const el of Array.from(root.querySelectorAll<HTMLElement>("*"))) {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue; // ignore collapsed/hidden nodes
      visible++;
      const x = Math.round(r.x);
      xs.add(x);
      // Group by a 4px vertical band so elements on the SAME visual row are compared together.
      // A real grid puts >= 7 day columns in one band; block flow puts one element per band.
      const band = Math.round(r.y / 4) * 4;
      if (!bands.has(band)) bands.set(band, new Set());
      bands.get(band)!.add(x);

      const cs = getComputedStyle(el);
      if (cs.position === "absolute" || cs.position === "sticky") positioned++;
      // NOTE: `box-sizing` is deliberately NOT used as a signal — Tailwind's preflight already sets
      // border-box on every element, so it is identical in both states and proves nothing.
      if (["flex", "table", "table-header-group", "table-row", "grid"].includes(cs.display)) flexOrTable++;
    }

    let maxBand = 0;
    let spread = 0;
    for (const set of bands.values()) {
      if (set.size > maxBand) {
        maxBand = set.size;
        const arr = [...set];
        spread = Math.max(...arr) - Math.min(...arr);
      }
    }
    const cw = root.getBoundingClientRect().width;
    return { visible, distinctX: xs.size, maxBand, spreadPct: cw ? Math.round((spread / cw) * 100) : 0, positioned, flexOrTable };
  });
}

/** P1–P4, applied to every row. `where` names the exact matrix cell so a failure is self-locating. */
function expectLaidOut(geo: Geo, where: string, view: string) {
  // P1 — horizontal distribution: a laid-out calendar occupies many distinct x-offsets.
  expect(geo.distinctX, `${where}: P1 distinct x-offsets (collapsed baseline is 4)`).toBeGreaterThanOrEqual(8);
  // P2 — row band: several elements share a row while differing in x. Block flow cannot produce this.
  expect(geo.maxBand, `${where}: P2 widest row band (collapsed baseline is 2)`).toBeGreaterThanOrEqual(3);
  // P4 — formatting context: skeleton.css is the ONLY source of these. Collapsed measures exactly 0.
  expect(geo.positioned, `${where}: P4a positioned descendants (collapsed baseline is 0)`).toBeGreaterThanOrEqual(1);
  expect(geo.flexOrTable, `${where}: P4b flex/table descendants (collapsed baseline is 0)`).toBeGreaterThanOrEqual(5);

  // P3 — column geometry, asserted only where the view legitimately renders a 7-column grid. Day
  // view has one day column plus a time axis, and list view is a narrow table, so demanding seven
  // columns there would be false precision rather than a stronger test.
  if (view === "month" || view === "week") {
    expect(geo.maxBand, `${where}: P3a seven-column grid band`).toBeGreaterThanOrEqual(7);
    expect(geo.spreadPct, `${where}: P3b columns span the container`).toBeGreaterThanOrEqual(50);
  }
}

type Surface = "runs" | "run";
type Row = {
  surface: Surface;
  view: "day" | "week" | "month" | "list" | "range";
  dir: "ltr" | "rtl";
  appearance: "light" | "dark";
  style: "editorial" | "operational";
  width: number;
};

// THE EXACT MATRIX — a true pairwise covering array, not the Cartesian product.
//
// The full product is 2 surface × 5 view × 2 dir × 2 appearance × 2 style × 3 width = 240 rows,
// which buys nothing here: these axes are INDEPENDENT in the CSS. Direction is a `dir` attribute,
// appearance and style are separate `<html>` attributes, and width is the viewport — none of them
// interact with FullCalendar's structural layer, which is what this spec exists to protect.
//
// The 15 rows below are pairwise-COMPLETE: every one of the 15 axis pairs realises every one of its
// value combinations — all 103, verified exhaustively rather than by hand. An earlier 10-row
// draft looked sufficient and was not: it silently missed 14 combinations across view×appearance,
// view×style, and view×width. 15 rows is the true lower bound, since view×width alone requires
// 5 × 3 = 15 distinct pairings.
//
// What is deliberately NOT covered is 3-way and higher interactions. Given the independence above
// there is no mechanism for them to exist, and saying so explicitly is the point — an unstated
// bound reads as full coverage.
const MATRIX: Row[] = [
  { surface: "run",  view: "range", dir: "rtl", appearance: "dark",  style: "editorial",   width: 375 },
  { surface: "run",  view: "day",   dir: "ltr", appearance: "light", style: "operational", width: 768 },
  { surface: "runs", view: "list",  dir: "ltr", appearance: "dark",  style: "operational", width: 1280 },
  { surface: "runs", view: "month", dir: "rtl", appearance: "light", style: "editorial",   width: 768 },
  { surface: "runs", view: "week",  dir: "ltr", appearance: "light", style: "operational", width: 375 },
  { surface: "run",  view: "week",  dir: "rtl", appearance: "light", style: "editorial",   width: 1280 },
  { surface: "run",  view: "list",  dir: "ltr", appearance: "dark",  style: "editorial",   width: 768 },
  { surface: "run",  view: "month", dir: "rtl", appearance: "dark",  style: "operational", width: 375 },
  { surface: "runs", view: "day",   dir: "rtl", appearance: "dark",  style: "editorial",   width: 375 },
  { surface: "runs", view: "range", dir: "ltr", appearance: "light", style: "operational", width: 768 },
  { surface: "run",  view: "list",  dir: "rtl", appearance: "light", style: "editorial",   width: 375 },
  { surface: "run",  view: "month", dir: "ltr", appearance: "dark",  style: "editorial",   width: 1280 },
  { surface: "runs", view: "week",  dir: "ltr", appearance: "dark",  style: "operational", width: 768 },
  { surface: "runs", view: "day",   dir: "rtl", appearance: "dark",  style: "operational", width: 1280 },
  { surface: "run",  view: "range", dir: "rtl", appearance: "light", style: "editorial",   width: 1280 },
];

/** The first run the SERVER reports as placed. An unplaced run has no window to project, so the
 *  selected-run calendar correctly renders its "unplaced" branch instead of a grid — measuring that
 *  would prove nothing. Fails loudly rather than skipping: a P0 gate that can silently not run is
 *  the same class of false green this spec was written to eliminate. */
async function placedRun(request: import("@playwright/test").APIRequestContext): Promise<string> {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  const placed = (rows as { round_id: string; starts_on?: string | null }[]).filter((r) => r.starts_on);
  expect(placed.length, "fixture must expose at least one PLACED run for the selected-run calendar").toBeGreaterThan(0);
  return placed[0].round_id;
}

for (const row of MATRIX) {
  const where = `${row.surface}/${row.view} ${row.dir} ${row.appearance} ${row.style} @${row.width}`;

  test(`FullCalendar renders real geometry — ${where} (#340)`, async ({ page, request }) => {
    // Appearance and schedule style are applied through the app's OWN pre-paint restore path
    // (the allowlisted local keys layout.tsx reads), not by forcing attributes. That keeps the test
    // honest about the resolved-state contract and works on the selected-run route, which does not
    // render the shell's toggles.
    await page.addInitScript(
      ([ak, av, sk, sv]) => {
        try { localStorage.setItem(ak, av); localStorage.setItem(sk, sv); } catch { /* storage denied */ }
      },
      [APPEARANCE_KEY, row.appearance, SCHEDULE_STYLE_KEY, row.style] as const,
    );
    await page.setViewportSize({ width: row.width, height: 900 });

    const scope = row.surface === "runs" ? "runs" : await placedRun(request);
    const path = row.surface === "runs" ? `/?v_runs=${row.view}` : `/runs/${encodeURIComponent(scope)}?v_${scope}=${row.view}`;
    const testId = row.surface === "runs" ? "runs-calendar-grid" : "run-schedule-calendar";

    await page.goto(`${WB_URL}${path}`);
    if (row.dir === "rtl") await page.evaluate(() => document.documentElement.setAttribute("dir", "rtl"));

    // The resolved presentation state actually took effect …
    await expect(page.locator("html")).toHaveAttribute("data-theme", row.appearance);
    await expect(page.locator("html")).toHaveAttribute("data-schedule-style", row.style);
    // … and the surface reached the requested view rather than silently falling back.
    const root = page.getByTestId(testId);
    await expect(root).toBeVisible();
    await expect(root).toHaveAttribute("data-view", row.view);

    // Geometry settles a frame after the view switch; poll the cheapest decisive signal rather than
    // sleeping, so this stays deterministic under the serial/zero-retry contract.
    await expect
      .poll(async () => (await geometry(page, testId)).flexOrTable, { message: `${where}: calendar never laid out` })
      .toBeGreaterThanOrEqual(5);

    expectLaidOut(await geometry(page, testId), where, row.view);

    // The page itself must never scroll horizontally — the grid scrolls inside its own container.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${where}: horizontal viewport overflow`).toBeLessThanOrEqual(0);
  });
}

// The geometry assertions above prove the calendar is LAID OUT. They cannot prove it is THEMED:
// a broken var() chain or an unresolvable color-mix would leave every P1–P4 bound satisfied while
// the calendar rendered in the package's stock palette — or in nothing at all. That would be the
// same false green this spec exists to eliminate, rebuilt one layer up. So the bridge is asserted
// directly: FullCalendar's own variables must RESOLVE to the V2 tokens, and must flip with
// appearance through Tanaghom's existing precedence rather than any second switch.
async function themeVars(page: Page) {
  return page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const v = (n: string) => cs.getPropertyValue(n).trim();
    // Resolve the var() chain the way the browser does, not by string comparison.
    const probe = document.createElement("div");
    probe.style.cssText = "background:var(--fc-classic-background);color:var(--fc-classic-foreground)";
    document.body.appendChild(probe);
    const p = getComputedStyle(probe);
    const out = {
      fcBackground: v("--fc-classic-background"),
      tokenCard: v("--color-card"),
      fcForeground: v("--fc-classic-foreground"),
      tokenFg: v("--color-fg"),
      computedBg: p.backgroundColor,
      computedFg: p.color,
      deadV6: v("--fc-page-bg-color"),
    };
    probe.remove();
    return out;
  });
}

test("FullCalendar variables resolve to V2 tokens and follow appearance — one authority (#340)", async ({ page }) => {
  const read = async (appearance: "light" | "dark") => {
    await page.addInitScript(
      ([k, v]) => { try { localStorage.setItem(k, v); } catch { /* storage denied */ } },
      [APPEARANCE_KEY, appearance] as const,
    );
    await page.goto(`${WB_URL}/?v_runs=month`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", appearance);
    await expect(page.getByTestId("runs-calendar-grid")).toBeVisible();
    return themeVars(page);
  };

  const light = await read("light");
  const dark = await read("dark");

  // The bridge is live: FullCalendar's variable IS the V2 token, in both modes.
  expect(light.fcBackground, "light: --fc-classic-background must resolve to --color-card").toBe(light.tokenCard);
  expect(dark.fcBackground, "dark: --fc-classic-background must resolve to --color-card").toBe(dark.tokenCard);
  expect(light.fcForeground).toBe(light.tokenFg);
  expect(dark.fcForeground).toBe(dark.tokenFg);
  // And it actually resolves to a real paint value rather than an empty/invalid chain.
  expect(light.computedBg).toMatch(/^(oklch|rgb)/);
  expect(dark.computedBg).toMatch(/^(oklch|rgb)/);

  // Appearance genuinely changes the calendar's colours — a single :root block is sufficient
  // precisely BECAUSE the underlying tokens flip. If these matched, the bridge would be inert.
  expect(dark.computedBg, "calendar background must differ between light and dark").not.toBe(light.computedBg);
  expect(dark.computedFg, "calendar foreground must differ between light and dark").not.toBe(light.computedFg);

  // The v6-generation names are gone, not merely shadowed. Leaving them would invite a future
  // reader to "fix" theming by editing variables the installed package never reads.
  expect(light.deadV6, "dead v6 --fc-page-bg-color must not be reintroduced").toBe("");
});

// Operability, asserted because directive scope 3 names it and NOTHING in the suite covered it —
// a grep for focus/Tab/outline assertions across every spec returned no matches. A calendar with
// perfect geometry that cannot be tabbed through is still not usable.
//
// What this does and does not prove, measured rather than reasoned:
//
//   • The focus RING itself does not depend on the package CSS. FullCalendar's toolbar buttons are
//     plain <button>s, so `globals.css`'s `:where(a, button, ...):focus-visible` rule reaches them
//     unaided — with the package CSS removed the ring is still `solid 2px var(--color-focus)`. With
//     it loaded the ring is `solid 3px`: the theme's class-specificity outline width beats the
//     zero-specificity `:where()` rule, and the colour arrives via `--fc-classic-button-outline`.
//
//   • The TEST nonetheless fails without the package CSS, because it first waits for the calendar
//     to be laid out. That wait is deliberate — focus on an unrendered calendar proves nothing —
//     but it means the failure is inherited from the layout precondition, NOT evidence that focus
//     styling regressed.
//
// So P1–P4 remain the only real detector of missing structural CSS. This test's own contribution is
// operability: that the controls exist, take focus perceivably, and do not trap Tab.
test("calendar toolbar controls are keyboard-reachable and visibly focused (#340)", async ({ page }) => {
  await page.goto(`${WB_URL}/?v_runs=month`);
  const grid = page.getByTestId("runs-calendar-grid");
  await expect(grid).toBeVisible();
  await expect.poll(async () => (await geometry(page, "runs-calendar-grid")).flexOrTable).toBeGreaterThanOrEqual(5);

  // Place focus on the calendar's first control directly, then assert Tab moves it: that covers
  // both halves of "operable" without depending on how many shell controls precede the calendar in
  // tab order, which would make the test brittle to unrelated layout changes.
  const buttons = grid.locator("button");
  const count = await buttons.count();
  expect(count, "FullCalendar must render its toolbar controls").toBeGreaterThan(0);

  await buttons.first().focus();
  const focused = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return null;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName,
      inCalendar: !!el.closest('[data-testid="runs-calendar-grid"]'),
      // A control with zero area cannot be seen or clicked, focused or not.
      hasArea: r.width >= 1 && r.height >= 1,
      // Focus must be PERCEIVABLE: an outline, a ring, or a visible box-shadow.
      outlineWidth: parseFloat(cs.outlineWidth) || 0,
      outlineStyle: cs.outlineStyle,
      boxShadow: cs.boxShadow,
    };
  });

  expect(focused, "an element must be focused").not.toBeNull();
  expect(focused!.inCalendar, "focus must land inside the calendar").toBe(true);
  expect(focused!.hasArea, "the focused control must be visible").toBe(true);
  const perceivable =
    (focused!.outlineStyle !== "none" && focused!.outlineWidth > 0) ||
    (focused!.boxShadow !== "none" && focused!.boxShadow !== "");
  expect(perceivable, `focus must be perceivable (outline/ring), got ${JSON.stringify(focused)}`).toBe(true);

  // Tabbing must MOVE focus — a control that traps or swallows Tab is not navigable.
  await page.keyboard.press("Tab");
  const moved = await page.evaluate(() => document.activeElement?.tagName ?? null);
  expect(moved, "Tab must move focus to another element").not.toBeNull();
});

// Editorial/Operational drives only two density knobs (--wb-card-pad / --wb-list-gap), applied via
// stable testids to the coverage and schedule-cell lists — NEVER to a calendar. Preserving that is
// the requirement; adding calendar density styling would be unauthorised redesign. This pins the
// axis as inert on the calendar so a future change cannot quietly extend it there.
test("schedule style leaves calendar geometry untouched — presentation axis stays inert (#340)", async ({ page }) => {
  const read = async (style: "editorial" | "operational") => {
    await page.addInitScript(
      ([k, v]) => { try { localStorage.setItem(k, v); } catch { /* storage denied */ } },
      [SCHEDULE_STYLE_KEY, style] as const,
    );
    await page.goto(`${WB_URL}/?v_runs=month`);
    await expect(page.locator("html")).toHaveAttribute("data-schedule-style", style);
    await expect(page.getByTestId("runs-calendar-grid")).toBeVisible();
    await expect.poll(async () => (await geometry(page, "runs-calendar-grid")).flexOrTable).toBeGreaterThanOrEqual(5);
    return geometry(page, "runs-calendar-grid");
  };

  const operational = await read("operational");
  const editorial = await read("editorial");

  expect(editorial.distinctX, "column layout must not shift with schedule style").toBe(operational.distinctX);
  expect(editorial.maxBand, "row banding must not shift with schedule style").toBe(operational.maxBand);
  expect(editorial.spreadPct, "column spread must not shift with schedule style").toBe(operational.spreadPct);
});
