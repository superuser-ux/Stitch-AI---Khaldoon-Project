import { test, expect, type Page } from "@playwright/test";
import { reseedScriptRound } from "./seed-script";

async function gotoRSCR(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RSCR").click();
  await page.waitForLoadState("networkidle");
}

test.beforeEach(() => reseedScriptRound());

test("script stage shows script code, framework, and review actions", async ({ page }) => {
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();

  const card = page.getByTestId("card-RSCR-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await expect(card).toContainText(/script code/i);
  await expect(card).toContainText(/framework:/i);
  await expect(card).toContainText(/lens:/i);
  await expect(card).toContainText(/approve/i);
  await expect(card).toContainText(/request change/i);
  await expect(card).toContainText(/drop \(recoverable\)/i);
  await expect(card).toContainText(/show script/i);
});

test("script stage can reveal persisted script content inline", async ({ page }) => {
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();

  const card = page.getByTestId("card-RSCR-1");
  await expect(card).toBeVisible({ timeout: 20000 });
  await card.getByText("show script", { exact: true }).click();
  await expect(card).toContainText("نص السكربت الأول");
  await expect(card).toContainText("سطر أخير");
});

test("script grid keeps structured sections readable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1400 });
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();
  await page.getByRole("button", { name: "Grid" }).click();

  const firstCard = page.getByTestId("card-RSCR-1");
  const secondCard = page.getByTestId("card-RSCR-2");

  await expect(firstCard).toBeVisible({ timeout: 20000 });
  await expect(secondCard).toBeVisible({ timeout: 20000 });
  await expect(firstCard).toContainText(/beat flow/i);
  await expect(firstCard).toContainText(/performance direction/i);
  await expect(firstCard).toContainText(/production handoff preview/i);
  await expect(secondCard).toContainText(/panel flow/i);
  await expect(secondCard).toContainText(/layout direction/i);

  const firstWidth = await firstCard.evaluate((node) => node.getBoundingClientRect().width);
  expect(firstWidth).toBeGreaterThan(430);

  const overflow = await firstCard.evaluate((node) => ({
    clientWidth: node.clientWidth,
    scrollWidth: node.scrollWidth,
  }));
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 2);
});

test("script grid stays single-column and avoids horizontal overflow on narrower viewports", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 1400 });
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();
  await page.getByRole("button", { name: "Grid" }).click();

  const firstCard = page.getByTestId("card-RSCR-1");
  await expect(firstCard).toBeVisible({ timeout: 20000 });
  await expect(firstCard).toContainText(/beat flow/i);
  await expect(firstCard).toContainText(/production handoff preview/i);

  const pageOverflow = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(pageOverflow.scrollWidth).toBeLessThanOrEqual(pageOverflow.innerWidth + 2);

  const cardOverflow = await firstCard.evaluate((node) => ({
    clientWidth: node.clientWidth,
    scrollWidth: node.scrollWidth,
  }));
  expect(cardOverflow.scrollWidth).toBeLessThanOrEqual(cardOverflow.clientWidth + 2);
});

// #149 (#146 S2) / #177 — script structure beat labels come from the format's canonical registry
// (production_rules.structure step→label), not a fixed UI dict. Deterministic RSCR fixture:
//   RSCR-2 Carousel  — registry structure (slide_1…slide_7) → registry labels render
//   RSCR-3 Hero Reel — registry 10-beat structure (60.viral.01, seeded by #177) → registry labels
//   RSCR-1 Hero Reel — OLD 4-beat script from before the registry fix → stale disclosure (#177)
test("script structure labels are registry-driven; managed Hero Reel renders the client framework (#149/#177)", async ({ page }) => {
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();

  const carousel = page.getByTestId("card-RSCR-2");   // Carousel — registry 7-slide framework
  await expect(carousel).toBeVisible({ timeout: 20000 });
  // AFTER #149: the slide_* beats carry the registry labels for the Carousel framework.
  await expect(carousel).toContainText("Concept Anchor");
  await expect(carousel).toContainText("Human Proof");
  await expect(carousel).toContainText("Practical Bridge");
  await expect(carousel).toContainText("Reflective CTA");
  // BEFORE #149 the raw registry keys would have been title-cased ("Slide 2", "Slide 3", …).
  // Prove the labels are registry-sourced, not a generic key transform.
  await expect(carousel).not.toContainText(/slide 2/i);
  await expect(carousel).not.toContainText(/slide 7/i);

  // #177 — Hero Reel with the managed structure: real 60.viral.01 beat labels, no generic
  // BUILD/TURN/CLOSE, and no disclosure badge of any kind (it IS the client framework).
  const heroManaged = page.getByTestId("card-RSCR-3");
  await expect(heroManaged).toBeVisible({ timeout: 20000 });
  await expect(heroManaged).toContainText("Micro-Story");
  await expect(heroManaged).toContainText("Cognitive Flip");
  await expect(heroManaged).toContainText("Killer Quote");
  await expect(heroManaged).toContainText("Viral Ending");
  await expect(heroManaged).not.toContainText("Build");
  await expect(page.getByTestId("structure-stale-RSCR-3")).toHaveCount(0);
  await expect(page.getByTestId("structure-fallback-RSCR-3")).toHaveCount(0);
});

// #177 — fallback/legacy/stale structure is DISCLOSED, never silently presented as the client
// framework, and the beat count is truthful about the hook promoted to the card headline.
test("structure fallback, legacy, and stale states are visibly disclosed; counts are truthful (#177)", async ({ page }) => {
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();

  // RSCR-1 — Hero Reel generated BEFORE the registry fix (4-beat keys): the registry now has a
  // 10-beat structure, so the card must say the script uses an older structure.
  const heroStale = page.getByTestId("card-RSCR-1");
  await expect(heroStale).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("structure-stale-RSCR-1"))
    .toContainText("Generated with older structure — regenerate for current framework");
  // its count must say generic "structured beats", never "framework steps"
  await expect(page.getByTestId("structure-count-RSCR-1")).toContainText("structured beats");
  await expect(page.getByTestId("structure-count-RSCR-1")).not.toContainText("framework step");

  // RSCR-4 — Pic + Caption is explicitly legacy in the registry (no client framework).
  await expect(page.getByTestId("structure-legacy-RSCR-4"))
    .toContainText("Legacy format — no client framework configured");

  // RSCR-2 — Carousel: all 7 slides accounted for; the promoted hook is explained, not omitted.
  await expect(page.getByTestId("structure-count-RSCR-2")).toContainText("7 framework steps");
  await expect(page.getByTestId("structure-promoted-RSCR-2")).toContainText("shown as the headline");

  // RSCR-3 — managed Hero Reel: 10 framework steps, promoted opening explained.
  await expect(page.getByTestId("structure-count-RSCR-3")).toContainText("10 framework steps");
  await expect(page.getByTestId("structure-promoted-RSCR-3")).toBeVisible();
});

// #177 — the methodology admin distinguishes configured structure from missing/legacy state so an
// operator can tell missing client data apart from system fallback.
test("methodology admin discloses configured vs legacy framework state (#177)", async ({ page }) => {
  await page.goto("/admin/methodology");
  await page.waitForLoadState("networkidle");
  // configured formats state their step count explicitly (Hero Reel 10, Carousel 7, 3sec 4)
  const counts = page.getByTestId("framework-structure-count");
  await expect(counts.filter({ hasText: "10-step structure configured" })).toHaveCount(1);
  await expect(counts.filter({ hasText: "7-step structure configured" })).toHaveCount(1);
  await expect(counts.filter({ hasText: "4-step structure configured" })).toHaveCount(1);
  // the legacy format says so instead of rendering nothing
  await expect(page.getByTestId("framework-legacy").first())
    .toContainText("Legacy carry-forward — no client framework configured");

  // #184 — minimal truthful disclosure of the ACTIVE topic-repetition policy (strict default
  // unless a managed row exists; either way the effective scope + mode state is stated).
  const repPolicy = page.getByTestId("repetition-policy");
  await expect(repPolicy).toBeVisible();
  await expect(page.getByTestId("repetition-policy-scope")).toContainText(/no same-topic reuse · scope: \w+|dedup disabled/);
  await expect(page.getByTestId("repetition-policy-source")).toContainText(/managed|production default/);
});

// #154 (#151 slice 1) — truthful script model attribution on the review card. RSCR-2 persists a
// provider:model label (surfaced verbatim from script.model); RSCR-1 persists none, so the card
// must say so explicitly instead of inferring or hiding it.
test("script cards surface the persisted model, or an explicit not-recorded state (#154)", async ({ page }) => {
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();

  const withModel = page.getByTestId("card-RSCR-2");
  await expect(withModel).toBeVisible({ timeout: 20000 });
  await expect(withModel.getByTestId("script-model-RSCR-2")).toHaveText("groq:llama-e2e");

  const withoutModel = page.getByTestId("card-RSCR-1");
  await expect(withoutModel).toBeVisible({ timeout: 20000 });
  await expect(withoutModel.getByTestId("script-model-missing-RSCR-1")).toContainText(/model not recorded/i);
  await expect(withoutModel.getByTestId("script-model-RSCR-1")).toHaveCount(0);
});

// #157 (#151 slice 2) — dialect TARGET CONTEXT is a system/stage-level statement of intent shown on
// every script card, kept strictly separate from the needs_native_review REVIEW-STATE signal.
// RSCR-1 is seeded with needs_native_review=true, RSCR-2 with false: both show the same target,
// only RSCR-1 shows the review-state badge, and neither badge claims per-revision verification.
test("dialect target context is stage-level intent, separate from the native-review signal (#157)", async ({ page }) => {
  await gotoRSCR(page);
  await page.getByTestId("nav-script").click();

  const flagged = page.getByTestId("card-RSCR-1");
  await expect(flagged).toBeVisible({ timeout: 20000 });
  await expect(flagged.getByTestId("script-target-RSCR-1")).toContainText("Arabic (Palestinian dialect / ar-PS)");
  await expect(flagged.getByTestId("script-native-review-RSCR-1")).toContainText(/native review/i);

  const unflagged = page.getByTestId("card-RSCR-2");
  await expect(unflagged).toBeVisible({ timeout: 20000 });
  // target context shows regardless of review state (it is intent, not a quality verdict)...
  await expect(unflagged.getByTestId("script-target-RSCR-2")).toContainText("Arabic (Palestinian dialect / ar-PS)");
  // ...and the review-state signal renders ONLY when persisted true — the two are independent.
  await expect(unflagged.getByTestId("script-native-review-RSCR-2")).toHaveCount(0);

  // wording honesty: the target badge states intent ("target"), never verification.
  await expect(flagged.getByTestId("script-target-RSCR-1")).toContainText(/target/i);
  await expect(flagged.getByTestId("script-target-RSCR-1")).not.toContainText(/verified|confirmed|passed/i);
});

// #159 (#54 slice 1) — mixed Arabic/English presentation on script cards. The blueprint header's
// badge cluster (#149 format + #157 target/native-review + #154 model) must read as ONE wrapped
// group with no auto-margin dead gap, and the English "Topic through-line" label must sit ABOVE
// the Arabic quote (inline, the RTL hero column made it trail mid-flow). Checked at the desktop
// two-column width and the repo's 820px narrow convention.
for (const width of [1440, 820]) {
  test(`mixed-language card presentation stays clean at ${width}px (#159)`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1400 });
    await gotoRSCR(page);
    await page.getByTestId("nav-script").click();

    const card = page.getByTestId("card-RSCR-1");
    await expect(card).toBeVisible({ timeout: 20000 });

    // all truthfulness badges remain present and visible (semantics untouched)
    for (const id of ["script-target-RSCR-1", "script-native-review-RSCR-1", "script-model-missing-RSCR-1"]) {
      await expect(card.getByTestId(id)).toBeVisible();
    }

    // the model badge flows with the cluster: on a shared row it must not be flung to the far
    // edge by an auto margin (gap to the previous badge stays small), and rows never overlap.
    const native = await card.getByTestId("script-native-review-RSCR-1").boundingBox();
    const model = await card.getByTestId("script-model-missing-RSCR-1").boundingBox();
    expect(native && model).toBeTruthy();
    const sameRow = Math.abs(native!.y - model!.y) < native!.height / 2;
    if (sameRow) expect(model!.x - (native!.x + native!.width)).toBeLessThan(24);

    // through-line: English label stacked ABOVE the Arabic quote, not inline after it
    const label = await card.getByTestId("topic-throughline-label-RSCR-1").boundingBox();
    const quote = await card.getByTestId("topic-throughline-text-RSCR-1").boundingBox();
    expect(label && quote).toBeTruthy();
    expect(label!.y + label!.height).toBeLessThanOrEqual(quote!.y + 1);

    // and the card still never scrolls horizontally
    const overflow = await card.evaluate((n) => ({ c: n.clientWidth, s: n.scrollWidth }));
    expect(overflow.s).toBeLessThanOrEqual(overflow.c + 2);
  });
}
