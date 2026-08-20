import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseed } from "./seed";

// #134 (count contract #131, Slice B) — the run-level funnel strip is READ-ONLY explanatory UI:
// it renders for the current round, its numbers equal GET /rounds/{id}/funnel, it never gains
// drill-in affordances, and it never feeds or replaces the stage-level disposition chips
// (the two families of numbers legitimately DIFFER — that difference is the feature).
const API = process.env.API_URL || "http://localhost:8009";
const funnel = async (r: APIRequestContext) =>
  (await r.get(`${API}/rounds/RE2E/funnel`)).json();

async function startReview(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible();
}

async function requestChange(page: Page, slot: string, comment: string) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await page.evaluate((testId) => {
      const node = document.querySelector(`[data-testid="${testId}"]`);
      (node as HTMLElement | null)?.click();
    }, `request-${slot}`);
    if (await page.getByTestId(`change-text-${slot}`).count()) break;
    await page.waitForTimeout(250);
  }
  await expect.poll(async () => await page.getByTestId(`change-text-${slot}`).count()).toBe(1);
  await page.getByTestId(`change-text-${slot}`).fill(comment);
  await page.getByTestId(`submit-change-${slot}`).evaluate((node) => {
    (node as HTMLElement).click();
  });
  await expect(page.getByTestId("toast")).toBeVisible();
}

test.beforeEach(() => reseed());

test("funnel strip renders for the round and equals the funnel endpoint", async ({ page, request }) => {
  await startReview(page);
  const strip = page.getByTestId("run-funnel-strip");
  await expect(strip).toBeVisible();
  const f = await funnel(request);
  await expect(strip).toHaveAttribute("data-funnel-total", String(f.total));
  for (const s of f.stages.filter((x: { entered: number }) => x.entered > 0)) {
    await expect(page.getByTestId(`funnel-${s.stage}`)).toHaveAttribute("data-entered", String(s.entered));
  }
  // read-only by contract: no drill-in, no clickable chips, no filter affordances
  expect(await strip.locator("button, a, [role=button], [role=link]").count()).toBe(0);
});

test("funnel and stage-level counts stay distinct (never conflated)", async ({ page, request }) => {
  await startReview(page);
  // stage total (single-snapshot #47 invariant) and funnel total start equal on the fresh fixture
  await expect(page.getByTestId("disposition-progress")).toHaveAttribute("data-total", "3");
  await expect(page.getByTestId("run-funnel-strip")).toHaveAttribute("data-funnel-total", "3");
  // one send-back: the STAGE view loses a visible card (2 in review) while the FUNNEL still
  // reports 3 entered at topics (now split 2 in + 1 awaiting) — different numbers, both true.
  await requestChange(page, "RE2E-2", "غيّر الزاوية");
  await expect(page.getByTestId("disposition-bar")).toContainText("2 in review");
  await expect.poll(async () => {
    const f = await funnel(request);
    const topic = f.stages.find((s: { stage: string }) => s.stage === "topic_review");
    return [topic.entered, topic.in_stage + topic.awaiting];
  }).toEqual([3, 3]);
  await expect(page.getByTestId("funnel-topic_review")).toHaveAttribute("data-entered", "3");
  // the #132 awaiting strip (stage-level reconciliation) is intact alongside the funnel
  await expect(page.getByTestId("awaiting-count-context")).toBeVisible();
  await expect(page.getByTestId("awaiting-count-context")).toContainText("1 awaiting regeneration");
  // and the stage progress anchor still reads the stage snapshot, not the funnel
  await expect(page.getByTestId("disposition-progress")).toHaveAttribute("data-total", "3");
});

// #218 — after Distribution/Publication the funnel no longer ends at a terminal "done": run
// completion stays truthful ("Run complete N") AND a compact, NON-INTERACTIVE
// Analytics → Learning → Optimize continuation shows the PLANNED (not connected) next loop.
// The funnel is server-derived read-only display; a route double gives a deterministic completed
// state to prove the rendering (no engine/state/arithmetic change).
const COMPLETED_FUNNEL = {
  round_id: "RE2E", total: 3, completed: 3, terminal_status: "SCHEDULED",
  stages: [{ stage: "distribution_review", in_stage: 0, awaiting: 0, dropped: 0, advanced: 3, entered: 3 }],
};

// a PARTIAL run: some items reached terminal, but not all — this is NOT run completion.
const PARTIAL_FUNNEL = {
  round_id: "RE2E", total: 3, completed: 1, terminal_status: "SCHEDULED",
  stages: [{ stage: "distribution_review", in_stage: 1, awaiting: 1, dropped: 0, advanced: 1, entered: 3 }],
};

async function openWithFunnel(page: Page, payload: unknown) {
  await page.route(/\/gw\/rounds\/RE2E\/funnel/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) }));
  await startReview(page);
  await expect(page.getByTestId("run-funnel-strip")).toBeVisible();
}
async function openWithCompletedFunnel(page: Page) {
  await openWithFunnel(page, COMPLETED_FUNNEL);
}

test("a PARTIAL run (0 < completed < total) shows truthful progress, NOT Run complete or the next loop (#218)", async ({ page }) => {
  await openWithFunnel(page, PARTIAL_FUNNEL);
  const strip = page.getByTestId("run-funnel-strip");
  // truthful partial count, no terminal "done"
  await expect(page.getByTestId("run-partial-complete")).toBeVisible();
  await expect(page.getByTestId("run-partial-complete")).toContainText("1");
  await expect(page.getByTestId("run-partial-complete")).toContainText("completed");
  await expect(strip).not.toContainText(/\bdone\b/i);
  // NEITHER the run-completion truth NOR the planned next loop appears while the run is unfinished
  await expect(page.getByTestId("run-complete")).toHaveCount(0);
  await expect(page.getByTestId("run-lifecycle-tail")).toHaveCount(0);
  await expect(page.getByTestId("lifecycle-continuation")).toHaveCount(0);
});

test("a completed run shows Run complete + the planned Analytics→Learning→Optimize continuation, not a terminal 'done' (#218)", async ({ page }) => {
  await openWithCompletedFunnel(page);
  const strip = page.getByTestId("run-funnel-strip");

  // run truth stays distinct + truthful, with the count preserved
  await expect(page.getByTestId("run-complete")).toBeVisible();
  await expect(page.getByTestId("run-complete")).toContainText("Run complete");
  await expect(page.getByTestId("run-complete")).toContainText("3");
  // the terminal user-facing "done" concept is gone from the strip
  await expect(strip).not.toContainText(/\bdone\b/i);

  // the planned continuation is present as ordered labels + one shared not-connected disclosure
  const tail = page.getByTestId("lifecycle-continuation");
  await expect(tail).toBeVisible();
  await expect(page.getByTestId("lifecycle-analytics")).toHaveText("Analytics");
  await expect(page.getByTestId("lifecycle-learning")).toHaveText("Learning");
  await expect(page.getByTestId("lifecycle-optimize")).toHaveText("Optimize");
  await expect(page.getByTestId("lifecycle-disclosure")).toContainText(/planned next loop, not connected/i);
  // must NOT claim the capabilities are running/live/active/enabled (the truthful "not connected"
  // disclosure is asserted above and is intentionally present)
  await expect(tail).not.toContainText(/\b(running|live|active|enabled)\b/i);

  // NON-INTERACTIVE: the whole strip (incl. the lifecycle labels) has zero links/buttons/controls
  expect(await strip.locator("a, button, [role=button], [role=link], [href]").count()).toBe(0);
  expect(await tail.locator("a, button, [role=button], [role=link], [href]").count()).toBe(0);
  // accessible as a labeled group, understandable without relying on color
  await expect(tail).toHaveAttribute("aria-label", /planned next loop, not connected/i);
});

for (const width of [1280, 375]) {
  test(`completed-run lifecycle continuation is readable with no page overflow at ${width}px (#218)`, async ({ page }) => {
    // navigate at desktop (the nav collapses behind a toggle at narrow widths), then resize to the
    // target width to test the completed-state layout
    await openWithCompletedFunnel(page);
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByTestId("lifecycle-continuation")).toBeVisible();
    await expect(page.getByTestId("run-complete")).toBeVisible();
    // no DOCUMENT-level horizontal overflow; lifecycle text is not clipped
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    for (const id of ["lifecycle-analytics", "lifecycle-learning", "lifecycle-optimize"]) {
      const box = await page.getByTestId(id).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
    }
  });
}
