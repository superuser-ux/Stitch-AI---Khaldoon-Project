import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #331 — the Topics stage: canonical COVERAGE ALLOCATIONS useful before topic copy exists, and the
// gated canonical manual Generate action.
//
// Two evidence lanes, kept explicitly separate:
//   - REAL READ PATH: the live API answers; allocations are assembled from server truth.
//   - INDUCED: route.fulfill forces a specific typed generation read model so each distinct generate
//     state is proven DETERMINISTICALLY (the repo's established technique — see operational-states).
//     No sleeps, no retries, no weakened assertions.

async function anyRun(request: import("@playwright/test").APIRequestContext): Promise<string> {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  expect(rows?.length, "the fixture must expose at least one run").toBeGreaterThan(0);
  // Prefer a run with slots so the allocation set is non-empty.
  for (const r of rows as { round_id: string }[]) {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    if ((d.slots?.length ?? 0) > 0) return r.round_id;
  }
  return rows[0].round_id;
}

test("Topics renders canonical coverage allocations before any topic copy exists (#331 A5/A6)", async ({ page, request }) => {
  const id = await anyRun(request);
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("topics-workspace")).toBeVisible();
  await expect(page.getByTestId("coverage-allocation-list")).toBeVisible();

  // One allocation per canonical slot — the COMPLETE coverage set, not a generated subset.
  await expect(page.getByTestId("coverage-allocation-list").locator(":scope > li"))
    .toHaveCount(detail.slots.length);

  const slot = detail.slots[0].slot_id as string;
  const row = page.getByTestId(`alloc-${slot}`);
  await expect(row).toBeVisible();
  // Each allocation exposes its client-facing context and its generation/review state truthfully.
  await expect(page.getByTestId(`alloc-code-${slot}`)).toBeVisible();          // schedule code (or "no governed code")
  await expect(page.getByTestId(`alloc-placement-${slot}`)).toBeVisible();     // date/time OR explicit unplaced
  await expect(page.getByTestId(`alloc-genstate-${slot}`)).toBeVisible();      // generation/review state
  await expect(page.getByTestId(`alloc-format-${slot}`)).toBeVisible();        // framework / content format
  await expect(page.getByTestId(`alloc-class-${slot}`)).toBeVisible();         // pillar / topic class
  await expect(page.getByTestId(`alloc-lang-${slot}`)).toBeVisible();          // language availability
});

test("target platform is disclosed as UNAVAILABLE, never fabricated (#331 A6)", async ({ page, request }) => {
  const id = await anyRun(request);
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
  const slot = detail.slots[0].slot_id as string;

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("coverage-platform-note")).toBeVisible();
  const platform = page.getByTestId(`alloc-platform-${slot}`);
  // The one field with no coverage read-model source is marked explicitly unavailable — not guessed.
  await expect(platform).toHaveAttribute("data-available", "false");
});

test("the view lens changes presentation only — the same allocation set (#331 A4)", async ({ page, request }) => {
  const id = await anyRun(request);
  const detail = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review&lens=list`);
  await expect(page.getByTestId("coverage-allocations")).toHaveAttribute("data-lens", "list");
  await expect(page.getByTestId("coverage-allocation-list").locator(":scope > li")).toHaveCount(detail.slots.length);

  // Grid is the same set, re-laid-out.
  await page.getByTestId("lens-grid").click();
  await expect(page.getByTestId("coverage-allocations")).toHaveAttribute("data-lens", "grid");
  await expect(page.getByTestId("coverage-allocation-list").locator(":scope > li")).toHaveCount(detail.slots.length);

  // Overview summarises the same truth (and still discloses the platform gap).
  await page.getByTestId("lens-overview").click();
  await expect(page.getByTestId("coverage-allocations")).toHaveAttribute("data-lens", "overview");
  await expect(page.getByTestId("coverage-count-total")).toContainText(String(detail.slots.length));
  await expect(page.getByTestId("coverage-platform-note")).toBeVisible();
});

// ---- INDUCED: the distinct generate states are gated on the typed read model (#331 A7) ----

const GEN = (over: Record<string, unknown>) => (route: import("@playwright/test").Route) =>
  route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ round_id: "X", stage2a_enabled: true, entry_mode: "manual",
      phase: "awaiting_trigger", jobs: [], results: [], counts: { accepted: 0, generated: 0 }, ...over }),
  });

test("manual + awaiting → Generate is OFFERED and posts the canonical #332 path (#331 A7)", async ({ page, request }) => {
  const id = await anyRun(request);
  await page.route(`**/gw/rounds/*/generation`, GEN({ entry_mode: "manual", phase: "awaiting_trigger" }));

  let posted = "";
  await page.route(`**/gw/rounds/*/stages/topic_review/generate`, async (route) => {
    posted = route.request().url();
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ job_id: "job-1", stage2a: true, activated: true }) });
  });

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  const action = page.getByTestId("topic-generate-action");
  await expect(action).toBeVisible();
  await action.click();

  // It goes through the CANONICAL generation route (stage topic_review) — never a second command path.
  expect(posted, "generate must post the canonical topic_review generation route").toContain("/stages/topic_review/generate");
  await expect(page.getByTestId("topic-generate-feedback")).toContainText(/started|under way/i);
});

test("automatic mode is observe-only — no manual Generate button (#331 A7)", async ({ page, request }) => {
  const id = await anyRun(request);
  await page.route(`**/gw/rounds/*/generation`, GEN({ entry_mode: "automatic", phase: "empty" }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("topic-generate-automatic")).toBeVisible();
  await expect(page.getByTestId("topic-generate-action")).toHaveCount(0);
});

test("not-provisioned shows a truthful state, no Generate button (#331 A7)", async ({ page, request }) => {
  const id = await anyRun(request);
  await page.route(`**/gw/rounds/*/generation`, GEN({ stage2a_enabled: false, entry_mode: null, phase: "empty" }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("topic-generate-unavailable")).toBeVisible();
  await expect(page.getByTestId("topic-generate-action")).toHaveCount(0);
});

test("busy (queued/running) needs no manual start — no Generate button (#331 A7)", async ({ page, request }) => {
  const id = await anyRun(request);
  await page.route(`**/gw/rounds/*/generation`, GEN({ entry_mode: "manual", phase: "running" }));
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("topic-generate-busy")).toBeVisible();
  await expect(page.getByTestId("topic-generate-action")).toHaveCount(0);
});

test("a coarse governed denial (403) is relayed verbatim, not a fabricated success (#331 A7)", async ({ page, request }) => {
  const id = await anyRun(request);
  await page.route(`**/gw/rounds/*/generation`, GEN({ entry_mode: "manual", phase: "awaiting_trigger" }));
  await page.route(`**/gw/rounds/*/stages/topic_review/generate`, (route) =>
    route.fulfill({ status: 403, contentType: "application/json",
      body: JSON.stringify({ detail: "not authorized to start this run's Topic generation" }) }));

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await page.getByTestId("topic-generate-action").click();
  const fb = page.getByTestId("topic-generate-feedback");
  await expect(fb).toHaveAttribute("data-kind", "error");
  await expect(fb).toContainText("not authorized");
});
