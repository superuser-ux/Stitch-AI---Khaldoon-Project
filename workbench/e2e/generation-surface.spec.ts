import { test, expect, type APIRequestContext } from "@playwright/test";
import { WB_URL, VIEWPORTS } from "./surfaces";

// #310 §F Level 2 — the read-only Stage 2A Topic-generation surface for a run.
//
// NON-SKIPPING BY CONSTRUCTION: the core assertions require a run that has actually generated
// Topics. `generatedRun()` DISCOVERS one through the real read path and throws if none exists — a
// skip would hide exactly the class of defect (empty render, silent fallback masking a failure)
// this surface exists to prevent.

/** A run whose Stage 2A read model reports at least one job AND at least one generated Topic. */
async function generatedRun(request: APIRequestContext) {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const res = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/generation`);
    if (!res.ok()) continue;
    const m = await res.json();
    if (m.stage2a_enabled && (m.jobs?.length ?? 0) > 0 && (m.counts?.generated ?? 0) > 0) {
      return { id: r.round_id as string, model: m };
    }
  }
  throw new Error("no run has generated Topics — the fixture must provision one; a skip would hide real defects");
}

/** A run with the generation read model but NO job yet (or the fallback), for the truthful empty state. */
async function nonGeneratedRun(request: APIRequestContext) {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const res = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/generation`);
    if (!res.ok()) continue;
    const m = await res.json();
    if ((m.jobs?.length ?? 0) === 0) return { id: r.round_id as string, model: m };
  }
  return null;                 // acceptable: not every fixture has an un-generated run
}

test("renders durable job truth + per-slot results + provenance disclosure (observe)", async ({ page, request }) => {
  const { id, model } = await generatedRun(request);

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-generation-seam")).toBeVisible();

  // The observe framing is present — this lane reports; it does not start/retry generation.
  await expect(page.getByTestId("wb-generation-observe-note")).toBeVisible();

  // Phase + counts are SERVER truth, verbatim (not inferred client-side).
  await expect(page.getByTestId("wb-generation-phase")).toHaveAttribute("data-phase", model.phase);
  await expect(page.getByTestId("wb-generation-counts"))
    .toHaveText(`${model.counts.generated}/${model.counts.accepted} topics`);

  // Every accepted slot is populated as a result row (complete population, not a subset). Direct
  // children only: #313 nests a per-item governance panel — with its own revision-history <li> list —
  // inside each row, so match `:scope > li`, not every descendant li.
  await expect(page.getByTestId("wb-generation-results").locator(":scope > li"))
    .toHaveCount(model.results.length);

  // A generated slot discloses its canonical Topic + resolved provenance.
  const generated = model.results.find((r: { topic: unknown }) => r.topic);
  expect(generated, "at least one generated result").toBeTruthy();
  const row = page.getByTestId(`wb-generation-result-${generated.slot_id}`);
  await expect(row).toBeVisible();
  await expect(row.getByTestId("wb-generation-topic-title")).toBeVisible();
  if (generated.provenance?.novelty_brief_version) {
    await expect(row.getByTestId("wb-generation-provenance"))
      .toContainText(generated.provenance.novelty_brief_version);
  }
});

test("no V2-initiated retry write — only a read-only recommendation for failed/partial", async ({ page, request }) => {
  const { id } = await generatedRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-generation-seam")).toBeVisible();
  // The seam never renders a retry SUBMIT control (V2 holds no authority binding); any retry is a
  // recommendation routed to the authorized surface. There is no button that posts a retry.
  await expect(page.locator("button[data-testid*='retry-generation']")).toHaveCount(0);
  await expect(page.locator("button[data-testid*='generation-retry-submit']")).toHaveCount(0);
});

test("truthful empty / fallback state (never a spinner, never a failure)", async ({ page, request }) => {
  const ng = await nonGeneratedRun(request);
  test.skip(!ng, "no un-generated run in this fixture (acceptable) — covered by the generated-run tests");
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(ng!.id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-generation-seam")).toBeVisible();
  // Either the pure-Stage-1 fallback or a real empty result — both are non-erroring, explicit states.
  const fallback = page.getByTestId("wb-generation-fallback");
  const empty = page.getByTestId("wb-generation-empty");
  await expect(fallback.or(empty)).toBeVisible();
  await expect(page.getByTestId("wb-generation-error")).toHaveCount(0);
});

test("responsive + RTL — the seam renders without horizontal overflow at every viewport", async ({ page, request }) => {
  const { id } = await generatedRun(request);
  for (const dir of ["ltr", "rtl"] as const) {
    for (const vp of VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
      await page.evaluate((d) => document.documentElement.setAttribute("dir", d), dir);
      await expect(page.getByTestId("wb-generation-seam")).toBeVisible();
      // The page body must never scroll horizontally (responsive contract).
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `no horizontal overflow at ${vp.label}/${dir}`).toBeLessThanOrEqual(1);
    }
  }
});
