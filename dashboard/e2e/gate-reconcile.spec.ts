import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";

// #265 — generated-slot → review-gate convergence, driven through the real UI.
// partial  = mid-generation (2 of 6 generated) + a seeded-legacy 2-target open gate: the surface
//            must offer GENERATE (never start-review), hide the gate, and show the held warning.
// legacy   = generation complete + the same seeded-legacy gate: one load reconciles it to the
//            complete population — six topic cards at desktop AND 375px, no duplicate decisions.
// The fixture is the isolated R265E round; RE2E and real rounds are never touched.

const API = process.env.API_URL || "http://localhost:8009";
const fixture = (mode: "partial" | "legacy" | "clean") =>
  execFileSync("docker", ["exec", "-w", "/work", "tanaghom-gateapi",
                          "python", "gates/e2e_seed_265.py", mode], { stdio: "ignore" });

async function openTopicStage(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-R265E").click();
  await page.waitForLoadState("networkidle");
  // the side nav collapses behind a toggle at narrow widths — reveal it if needed, then navigate
  const navBtn = page.getByTestId("nav-topic");
  if (!(await navBtn.isVisible().catch(() => false))) await page.getByTestId("nav-toggle").click();
  await navBtn.click();
  await page.waitForLoadState("networkidle");
}

test.afterAll(() => fixture("clean"));

test("mid-generation: generate offered (never start-review), gate hidden, held warning visible (#265)", async ({ page, request }) => {
  fixture("partial");
  await openTopicStage(page);

  // the stage offers generation — the start-review control must NOT exist mid-generation
  await expect(page.getByTestId("generate-action")).toBeVisible();
  await expect(page.getByTestId("open-gate")).toHaveCount(0);
  // the seeded-legacy open gate is held with an operator-visible truthful warning
  await expect(
    page.getByTestId("stage-warning").filter({ hasText: "held until generation completes" })
  ).toBeVisible();
  // no review cards render off the hidden partial gate
  await expect(page.getByTestId("card-R265E-1")).toHaveCount(0);

  // the read model backs the surface: generate state, no gate, truthful counts on both sides
  const ss = await (await request.get(`${API}/rounds/R265E/stages/topic_review/state`)).json();
  expect(ss.state).toBe("generate");
  expect(ss.gate_id).toBeNull();
  expect(ss.review_pending).toBe(2);
  expect(ss.pending_input).toBe(4);
});

for (const vp of [{ w: 1280, h: 900, label: "desktop" }, { w: 375, h: 812, label: "mobile" }] as const) {
  test(`legacy 2-of-6 gate reconciles on load — six topic cards at ${vp.w}px (${vp.label}) (#265)`, async ({ page, request }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: vp.w, height: vp.h });
    fixture("legacy");
    await openTopicStage(page);

    // one load converges the gate onto the COMPLETE eligible population — all six cards render
    for (const s of ["R265E-1", "R265E-2", "R265E-3", "R265E-4", "R265E-5", "R265E-6"]) {
      await expect(page.getByTestId(`card-${s}`)).toBeVisible({ timeout: 20_000 });
    }

    // stage state, gate target count, and funnel agree (the contradiction is gone)
    const ss = await (await request.get(`${API}/rounds/R265E/stages/topic_review/state`)).json();
    expect(ss.in_review).toBe(6);
    expect(ss.review_pending).toBe(6);
    expect(ss.reconciliation_ok).toBe(true);
    const fun = await (await request.get(`${API}/rounds/R265E/funnel`)).json();
    expect(fun.stages.find((x: { stage: string }) => x.stage === "topic_review").in_stage).toBe(6);
  });
}
