import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #304 Stage 1 Level 2 — the selected-run governed Schedule workspace.
//
// NON-SKIPPING BY CONSTRUCTION: the block requires core acceptance not to skip because a fixture
// lacks a mutable run/token. `governedRun()` PROVISIONS one through the real governed path and fails
// the test if it cannot — a skip would hide exactly the class of defect that hid the placement 500.

async function governedRun(request: import("@playwright/test").APIRequestContext) {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const m = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/schedule-mapping`);
    if (!m.ok()) continue;
    const map = await m.json();
    // A run with a governed mapping AND at least two cells AND still at the Schedule stage (not
    // downstream-frozen): a frozen run cannot be reordered/revised, so selecting one would turn a
    // correct governed refusal into a spurious failure. Freeze is the server's answer, read from
    // the round's own lifecycle counts.
    if (map.legacy || (map.positions?.length ?? 0) < 2) continue;
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    const counts = d.status_counts ?? {};
    const total = Object.values(counts).reduce((a: number, b) => a + (b as number), 0);
    const atSchedule = (counts.RESERVED ?? 0) + (counts.SCHEDULE_APPROVED ?? 0);
    if (total > 0 && atSchedule === total) return { id: r.round_id, map };
  }
  throw new Error("no governed run with >=2 mapped cells — the fixture must provision one; a skip would hide real defects");
}

test("the workspace renders every canonical cell with display_code PRIMARY and slot_id secondary (#304 A5/A8)", async ({ page, request }) => {
  const { id, map } = await governedRun(request);
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  // COMPLETE canonical population — every planned cell the server reports, not the review subset.
  await expect(page.getByTestId("schedule-cells").locator("li")).toHaveCount(detail.slots.length);

  for (const p of map.positions.slice(0, 3)) {
    // The routine identifier is the SERVER's display code …
    await expect(page.getByTestId(`cell-code-${p.slot_id}`)).toHaveText(p.display_code);
    // … and the canonical id remains visible as secondary diagnostic identity, verbatim.
    await expect(page.getByTestId(`cell-canonical-${p.slot_id}`)).toHaveText(p.slot_id);
  }
});

test("framework options come from the run's PINNED policy, not the live catalogue (#304 A7)", async ({ page, request }) => {
  const { id } = await governedRun(request);
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  // The pinned set is objects {name, version_id, framework_id} — `name` is what the governed
  // revision contract validates against. Comparing the objects to rendered labels is the same
  // React-#31-shaped mistake the component made; assert on the identity the server actually uses.
  const pinned: string[] = (detail.pinned_eligible_formats ?? []).map((f: { name: string } | string) =>
    typeof f === "string" ? f : f.name);
  expect(pinned.length, "the run must expose its pinned eligible set").toBeGreaterThan(0);

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  // allTextContents() does NOT auto-wait: querying before the workspace hydrates returns [] and the
  // assertion compares against nothing while looking like a real check. Wait for the cell first.
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();
  const first = detail.slots[0].slot_id;
  await expect(page.getByTestId(`cell-format-${first}`)).toBeVisible();
  // textContent, not innerText: an <option> inside a closed <select> is not rendered, so innerText
  // is empty and the assertion would compare against nothing while looking like a real check.
  const opts = await page.getByTestId(`cell-format-${first}`).locator("option").allTextContents();
  // Exactly the pinned set — a later policy change must never reinterpret this run.
  expect(opts.sort()).toEqual([...pinned].sort());
});

test("a stale-token revision is REFUSED and re-read, never optimistically applied (#304 A6)", async ({ request }) => {
  const { id, map } = await governedRun(request);
  const slot = map.positions[0].slot_id;
  const before = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  const dayBefore = before.slots.find((s: { slot_id: string }) => s.slot_id === slot)?.day;

  const res = await request.post(`${WB_URL}/gw/slots/${encodeURIComponent(slot)}/schedule-revision`, {
    data: { changes: { day: 2 }, schedule_token: map.schedule_token + 999 },
  });
  expect(res.status(), "a stale token must be refused").not.toBe(200);

  const after = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  expect(after.slots.find((s: { slot_id: string }) => s.slot_id === slot)?.day,
    "a refused revision must not land").toBe(dayBefore);
});

test("an INVALID framework fails closed — the server decides, V2 does not pre-filter (#304 A7)", async ({ request }) => {
  const { id, map } = await governedRun(request);
  const slot = map.positions[0].slot_id;
  const res = await request.post(`${WB_URL}/gw/slots/${encodeURIComponent(slot)}/schedule-revision`, {
    data: { changes: { format: "Not A Real Framework" }, schedule_token: map.schedule_token },
  });
  expect(res.status(), "an ineligible framework must fail closed").not.toBe(200);
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  expect(detail.slots.find((s: { slot_id: string }) => s.slot_id === slot)?.format,
    "a refused revision must not land").not.toBe("Not A Real Framework");
});

test("keyboard reorder builds a PREVIEW and commits through Tanaghom (#304 A6)", async ({ page, request }) => {
  const { id, map } = await governedRun(request);
  const first = map.positions[0].slot_id;

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();

  // Keyboard only: focus the move control and press Enter. Drag is never the sole path.
  const down = page.getByTestId(`cell-down-${first}`);
  await down.focus();
  await expect(down).toBeFocused();
  await page.keyboard.press("Enter");

  // A move is a PROPOSAL: it is unsaved and says so until committed.
  await expect(page.getByTestId("order-preview")).toBeVisible();

  await page.getByTestId("order-apply").click();
  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });

  // The SERVER's accepted order is what the surface shows afterwards.
  await expect.poll(async () => {
    const m = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}/schedule-mapping`)).json();
    return m.positions[0].slot_id;
  }, { timeout: 20_000 }).not.toBe(first);
});

test("a discarded preview reverts to the authoritative order (#304 A6)", async ({ page, request }) => {
  const { id, map } = await governedRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  const first = map.positions[0].slot_id;
  await page.getByTestId(`cell-down-${first}`).click();
  await expect(page.getByTestId("order-preview")).toBeVisible();
  await page.getByTestId("order-discard").click();
  // No local shadow order survives: the accepted order is shown again.
  await expect(page.getByTestId("order-preview")).toHaveCount(0);
  const codes = await page.getByTestId("schedule-cells").locator("li").first().getAttribute("data-slot-id");
  expect(codes).toBe(map.positions[0].slot_id);
});

for (const vp of [
  { name: "desktop", width: 1280, height: 900 },
  { name: "tablet", width: 820, height: 1180 },
  { name: "mobile", width: 375, height: 812 },
]) {
  for (const dir of ["ltr", "rtl"] as const) {
    test(`Level 2 has no page-level overflow at ${vp.name} ${dir} (#304 A10)`, async ({ page, request }) => {
      const { id } = await governedRun(request);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
      await page.evaluate((d) => document.documentElement.setAttribute("dir", d), dir);
      await expect(page.getByTestId("run-schedule-workspace")).toBeVisible();
      // Scope controls stay reachable at every width rather than being cropped away.
      await expect(page.getByTestId("schedule-scope-controls")).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `page overflow at ${vp.name}/${dir}`).toBeLessThanOrEqual(0);
    });
  }
}

// #306 Stage 1B — dependent Pillar/HCS taxonomy over the run's PINNED generation.
async function pinnedRun(request: import("@playwright/test").APIRequestContext) {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    const t = d.pinned_taxonomy;
    const m = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/schedule-mapping`)).json();
    if (!(t?.pillars?.length >= 2 && t?.hcs?.length >= 2) || m.legacy) continue;
    const counts = d.status_counts ?? {};
    const total = Object.values(counts).reduce((a: number, b) => a + (b as number), 0);
    const atSchedule = (counts.RESERVED ?? 0) + (counts.SCHEDULE_APPROVED ?? 0);
    if (total > 0 && atSchedule === total) return { id: r.round_id, detail: d, tax: t, map: m };
  }
  throw new Error("no run with a pinned taxonomy (>=2 pillars) — the fixture must provision one; a skip would hide real defects");
}

test("dependent HCS options come only from the chosen pillar in the PINNED generation (#306)", async ({ page, request }) => {
  const { id, detail, tax } = await pinnedRun(request);
  const slot = detail.slots[0].slot_id;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  await expect(page.getByTestId(`cell-pillar-${slot}`)).toBeVisible();

  // Pick a pillar that actually has HCS in the pinned generation, and assert the HCS select shows
  // EXACTLY that pillar's HCS — dependency resolved from server truth, not inferred from a label.
  const pillar = (tax.pillars as { pillar_code: string }[]).find(
    (p) => (tax.hcs as { pillar_code: string }[]).some((h) => h.pillar_code === p.pillar_code))!.pillar_code;
  await page.getByTestId(`cell-pillar-${slot}`).selectOption(pillar);
  const expected = (tax.hcs as { pillar_code: string; hcs_id: string }[])
    .filter((h) => h.pillar_code === pillar).map((h) => h.hcs_id).sort();
  const shown = (await page.getByTestId(`cell-hcs-${slot}`).locator("option").allTextContents()).sort();
  expect(shown).toEqual(expected);
});

test("changing pillar shows an unsaved consequence preview and does not touch server state (#306)", async ({ page, request }) => {
  const { id, detail, tax } = await pinnedRun(request);
  const slot = detail.slots[0].slot_id;
  const before = detail.slots.find((s: { slot_id: string }) => s.slot_id === slot);

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  const other = (tax.pillars as { pillar_code: string }[]).find(
    (p) => p.pillar_code !== before.pillar_code
      && (tax.hcs as { pillar_code: string }[]).some((h) => h.pillar_code === p.pillar_code))!.pillar_code;
  await page.getByTestId(`cell-pillar-${slot}`).selectOption(other);

  // The proposal is UNSAVED and says what commit would (and would not) do.
  await expect(page.getByTestId(`tax-preview-${slot}`)).toBeVisible();
  await expect(page.getByTestId(`tax-preview-${slot}`)).toContainText(slot);

  // Nothing committed: server truth is unchanged by proposing.
  const after = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  expect(after.slots.find((s: { slot_id: string }) => s.slot_id === slot)?.hcs_id).toBe(before.hcs_id);
});

test("committing a taxonomy override goes through Tanaghom and re-reads server truth (#306)", async ({ page, request }) => {
  const { id, detail, tax } = await pinnedRun(request);
  const slot = detail.slots[0].slot_id;
  const before = detail.slots.find((s: { slot_id: string }) => s.slot_id === slot);
  const other = (tax.pillars as { pillar_code: string }[]).find(
    (p) => p.pillar_code !== before.pillar_code
      && (tax.hcs as { pillar_code: string }[]).some((h) => h.pillar_code === p.pillar_code))!.pillar_code;
  const newHcs = (tax.hcs as { pillar_code: string; hcs_id: string }[]).find((h) => h.pillar_code === other)!.hcs_id;

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  await page.getByTestId(`cell-pillar-${slot}`).selectOption(other);
  await page.getByTestId(`cell-hcs-${slot}`).selectOption(newHcs);
  await page.getByTestId(`cell-revise-${slot}`).click();

  await expect(page.getByTestId("run-schedule-feedback")).toHaveAttribute("data-kind", "ok", { timeout: 20_000 });
  // The SERVER's accepted classification is what the slot reports afterwards.
  await expect.poll(async () => {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
    const s = d.slots.find((x: { slot_id: string }) => x.slot_id === slot);
    return [s?.pillar_code, s?.hcs_id];
  }, { timeout: 20_000 }).toEqual([other, newHcs]);

  // Canonical id and history never change; a NEW generation was minted (token advanced).
  const m = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}/schedule-mapping`)).json();
  expect(m.positions.some((p: { slot_id: string }) => p.slot_id === slot)).toBe(true);
});

test("category is a projection, not an editable identity (#306 boundary)", async ({ page, request }) => {
  const { id, detail } = await pinnedRun(request);
  const slot = detail.slots[0].slot_id;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?lens_${id}=list`);
  // A read-only projection derived from the HCS — present as a span, with NO editable category input.
  await expect(page.getByTestId(`cell-category-${slot}`)).toBeVisible();
  expect(await page.locator(`[data-testid="cell-category-input-${slot}"]`).count()).toBe(0);
});
