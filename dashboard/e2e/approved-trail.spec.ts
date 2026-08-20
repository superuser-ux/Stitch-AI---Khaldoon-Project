import { test, expect, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { reseedScriptRound } from "./seed-script";
import { execSync } from "node:child_process";

// #179 — durable approved-items trail. After items are approved & committed at a stage, the client
// must still see WHAT moved forward and WHERE it went — item-level, surviving reload, not just
// counts or the short-lived "just approved" acknowledgment. Server-derived from committed gate
// state (gates.selftest §14 proves the read model; this proves the surface).
test.beforeEach(() => reseed());

async function openTopicStage(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-topic").click();
  await page.waitForLoadState("networkidle");
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
}

test("approved items stay discoverable after commit and after reload (#179)", async ({ page }) => {
  test.setTimeout(180_000);
  await openTopicStage(page);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });

  // Before anything commits there is no trail.
  await expect(page.getByTestId("advanced-trail")).toHaveCount(0);

  // Per-item immediate approval commits RE2E-1 and it leaves the pending queue…
  await page.getByTestId("approve-RE2E-1").click();
  await expect(page.getByTestId("card-RE2E-1")).toBeHidden({ timeout: 20_000 });

  // …but it is NOT lost: the durable trail shows it, item-level, with recognisable detail.
  const trail = page.getByTestId("advanced-trail");
  await expect(trail).toBeVisible({ timeout: 20_000 });
  const item = page.getByTestId("advanced-item-RE2E-1");
  await expect(item).toBeVisible();
  // #219 — the trail now shows the canonical content code (same formatter as active cards),
  // default expanded mode; the raw slot_id still keys the row testid + full-density detail.
  await expect(page.getByTestId("advanced-code-RE2E-1")).toHaveText(/^P\d{2}-HS\d{2}-\d{2}\.\d{2}$/);
  await expect(item).toContainText("Hero Reel");
  await expect(page.getByTestId("advanced-location-RE2E-1")).toContainText(/Approved at Topics|Now in .* review/);

  // Reload: the trail is server-derived, so it survives (unlike the transient acknowledgment).
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-item-RE2E-1")).toBeVisible();

  // The trail is read-only: the ONLY buttons inside a row are non-mutating inspection affordances
  // (#237's openable detail, like the dropped lane's detail toggle) — never a mutation control.
  const rowButtons = page.getByTestId("advanced-item-RE2E-1").locator("button");
  for (let i = 0; i < (await rowButtons.count()); i++) {
    const tid = await rowButtons.nth(i).getAttribute("data-testid");
    expect(tid).toMatch(/^trail-inspect-/);
  }
});

test("a fully completed stage shows the full trail instead of reading empty/lost (#179)", async ({ page }) => {
  test.setTimeout(240_000);
  await openTopicStage(page);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });

  for (const slot of ["RE2E-1", "RE2E-2", "RE2E-3"]) {
    await page.getByTestId(`approve-${slot}`).click();
    await expect(page.getByTestId(`card-${slot}`)).toBeHidden({ timeout: 20_000 });
  }

  // Every item committed — the stage is complete, and the trail carries all three items.
  const trail = page.getByTestId("advanced-trail");
  await expect(trail).toBeVisible({ timeout: 20_000 });
  await expect(trail).toContainText("3 approved & moved forward");
  for (const slot of ["RE2E-1", "RE2E-2", "RE2E-3"]) {
    await expect(page.getByTestId(`advanced-item-${slot}`)).toBeVisible();
  }

  // Reload the completed stage: still not empty/lost.
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-trail")).toContainText("3 approved & moved forward");
  await expect(page.getByTestId("advanced-item-RE2E-2")).toBeVisible();
});

// #219 — a COMPLETED stage (targets.length === 0, advancedTrail.length > 0) must KEEP the density
// + ID-mode inspection controls, effective on the read-only trail, with no overflow/clipping and
// no mutation affordance, at desktop / ~656px / 375px.
const V4_EXPANDED = /^P\d{2}-HS\d{2}-\d{2}\.\d{2}$/;
const V4_COMPACT = /^\d{2}-\d{2}-\d{2}\.\d{2}$/;

async function completeTopicStage(page: Page) {
  await openTopicStage(page);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });
  for (const slot of ["RE2E-1", "RE2E-2", "RE2E-3"]) {
    await page.getByTestId(`approve-${slot}`).click();
    await expect(page.getByTestId(`card-${slot}`)).toBeHidden({ timeout: 20_000 });
  }
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
  // completed: no active review cards remain
  await expect(page.locator("[data-testid^=card-]")).toHaveCount(0);
}

test("completed stage keeps effective density + ID-mode inspection controls, read-only (#219)", async ({ page }) => {
  test.setTimeout(240_000);
  await completeTopicStage(page);

  // the controls that used to vanish at targets===0 are present and reachable
  const idSwitcher = page.getByTestId("idmode-switcher");
  const densitySwitcher = page.getByTestId("density-switcher");
  await expect(idSwitcher).toBeVisible();
  await expect(densitySwitcher).toBeVisible();
  await page.getByTestId("idmode-compact").focus();
  await expect(page.getByTestId("idmode-compact")).toBeFocused();   // keyboard reachable

  const code = page.getByTestId("advanced-code-RE2E-1");
  const item = page.getByTestId("advanced-item-RE2E-1");

  // ID modes are EFFECTIVE and canonically distinct (existing formatter; no fabrication)
  await page.getByTestId("idmode-expanded").click();
  const expanded = (await code.innerText()).trim();
  expect(expanded).toMatch(V4_EXPANDED);
  await page.getByTestId("idmode-compact").click();
  const compact = (await code.innerText()).trim();
  expect(compact).toMatch(V4_COMPACT);
  expect(compact).not.toBe(expanded);
  // Detailed keeps the expanded canonical label AND adds the descriptor (its materially-distinct part)
  await page.getByTestId("idmode-detailed").click();
  expect((await code.innerText()).trim()).toMatch(V4_EXPANDED);
  await expect(page.getByTestId("advanced-descriptor-RE2E-1")).toBeVisible();

  // density is EFFECTIVE and distinct: chip hides format, full reveals the attribution block
  await page.getByTestId("density-full").click();
  await expect(item).toHaveAttribute("data-density", "full");
  await expect(page.getByTestId("advanced-full-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("advanced-full-RE2E-1")).toContainText(/Approved by/i);
  await page.getByTestId("density-chip").click();
  await expect(item).toHaveAttribute("data-density", "chip");
  await expect(page.getByTestId("advanced-full-RE2E-1")).toHaveCount(0);
  await expect(item).not.toContainText("Hero Reel");   // chip trims the format badge
  await page.getByTestId("density-compact").click();
  await expect(item).toContainText("Hero Reel");         // compact restores it

  // read-only in EVERY mode: no mutation affordance anywhere in the trail (topic stage → no
  // publication control either). #237's inspect toggles are the ONLY allowed buttons — they open
  // read-only detail and never mutate.
  for (const d of ["chip", "compact", "full"]) {
    await page.getByTestId(`density-${d}`).click();
    const btns = page.getByTestId("advanced-trail").locator("button");
    for (let i = 0; i < (await btns.count()); i++) {
      expect(await btns.nth(i).getAttribute("data-testid")).toMatch(/^trail-inspect-/);
    }
  }
});

for (const width of [1280, 656, 375]) {
  test(`completed-stage controls + evidence fit with no document overflow at ${width}px (#219)`, async ({ page }) => {
    test.setTimeout(240_000);
    // navigate + complete at desktop (the nav collapses behind a toggle at narrow widths), then
    // resize to the target width to test the completed-state LAYOUT — the directive's ~656/375 case
    await completeTopicStage(page);
    await page.setViewportSize({ width, height: 900 });
    await page.getByTestId("density-full").click();
    await expect(page.getByTestId("idmode-switcher")).toBeVisible();
    await expect(page.getByTestId("density-switcher")).toBeVisible();
    await expect(page.getByTestId("advanced-item-RE2E-1")).toBeVisible();
    // no DOCUMENT-level horizontal overflow (the accepted internal header scroller is separate)
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    // the mode switchers remain usable (clickable) at this width
    await page.getByTestId("idmode-compact").click();
    await expect(page.getByTestId("advanced-code-RE2E-1")).toHaveText(V4_COMPACT);
  });
}

// #237 Slice A — approval changes CONTROLS, not inspection depth: an approved/advanced item stays
// openable to the same content definition the active card showed (topic text, rationale, approved
// revision + attribution, decision provenance), read-only, with truthful absence for detail that
// does not exist yet. Server projection: /slots/{id}/inspect (engine inspect_slot; selftests prove
// the read model + HTTP boundary — this proves the surface).
test("approved item opens to full read-only detail parity after the approval transition (#237)", async ({ page }) => {
  test.setTimeout(240_000);
  await openTopicStage(page);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });

  // capture the definition the ACTIVE card shows before approval (the parity baseline)
  const activeCardText = await page.getByTestId("card-RE2E-1").innerText();

  await page.getByTestId("approve-RE2E-1").click();
  await expect(page.getByTestId("card-RE2E-1")).toBeHidden({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });

  // the row is openable at ANY density — expand it
  await page.getByTestId("trail-inspect-toggle-RE2E-1").click();
  const panel = page.getByTestId("trail-inspect-RE2E-1");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("trail-inspect-readonly-RE2E-1")).toContainText(/read-only/i);

  // information parity with the active card: topic definition + rationale are the SAME truth
  const topicBlock = page.getByTestId("trail-inspect-topic-RE2E-1");
  await expect(topicBlock).toBeVisible();
  const hook = "خليك أقوى من خوفك";
  expect(activeCardText).toContain(hook);
  await expect(panel).toContainText(hook);
  await expect(page.getByTestId("trail-inspect-rationale-RE2E-1")).toContainText("because it matters");
  // the approved revision is labeled as approved (the slot_approval pin), never a bare status line
  await expect(topicBlock).toContainText(/approved/);

  // decision provenance is visible (who approved, at this stage)
  await expect(page.getByTestId("trail-inspect-decisions-RE2E-1")).toContainText(/approve/);

  // truthful absence — a topic-stage item has no script / assets / publications yet, and SDAM
  // lineage is explicitly "not surfaced", never silently implied
  await expect(page.getByTestId("trail-inspect-absent-script-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("trail-inspect-absent-assets-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("trail-inspect-absent-publications-RE2E-1")).toBeVisible();
  await expect(page.getByTestId("trail-inspect-absent-sdam-RE2E-1")).toBeVisible();

  // STRICTLY non-mutating: nothing inside the expanded panel edits, decides, regenerates,
  // reopens, or restores — for any principal (this slice introduces no eligibility decision)
  const panelButtons = panel.locator("button");
  for (let i = 0; i < (await panelButtons.count()); i++) {
    expect(await panelButtons.nth(i).getAttribute("data-testid")).toMatch(/^trail-inspect-/);
  }
  await expect(panel.locator("[data-testid^=approve-], [data-testid^=reject-], " +
    "[data-testid^=changes-], [data-testid^=regenerate-], [data-testid^=restore-], " +
    "textarea, input, select")).toHaveCount(0);

  // detail survives reload (server-derived projection, not client residue)
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("trail-inspect-toggle-RE2E-1").click();
  await expect(page.getByTestId("trail-inspect-RE2E-1")).toContainText("because it matters");
});

test("inspection stays available and read-only across density/ID modes and at 375px (#237)", async ({ page }) => {
  test.setTimeout(240_000);
  await completeTopicStage(page);

  // the openable affordance exists in EVERY density — including chip
  for (const d of ["chip", "compact", "full"]) {
    await page.getByTestId(`density-${d}`).click();
    await expect(page.getByTestId("trail-inspect-toggle-RE2E-2")).toBeVisible();
  }
  // and under every ID mode
  for (const m of ["expanded", "compact", "detailed"]) {
    await page.getByTestId(`idmode-${m}`).click();
    await expect(page.getByTestId("trail-inspect-toggle-RE2E-2")).toBeVisible();
  }

  // expand at chip density, then narrow to mobile: the SAME detail stays accessible, no overflow
  await page.getByTestId("density-chip").click();
  await page.getByTestId("trail-inspect-toggle-RE2E-2").click();
  await expect(page.getByTestId("trail-inspect-RE2E-2")).toContainText("because it matters");
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByTestId("trail-inspect-RE2E-2")).toBeVisible();
  await expect(page.getByTestId("trail-inspect-rationale-RE2E-2")).toBeVisible();
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

// #237 review P1 (adversarial) — slot.topic_angle and the pinned topic.text_ar are independently
// persisted and can DIVERGE (live edits/restores move the slot body while the approval pin stays).
// Parity means BOTH truths stay visible with labels — the approved body is never silently replaced
// by the live one, and the live one is never dropped.
test("a diverged live slot body and the approved topic body BOTH stay visible (#237)", async ({ page }) => {
  test.setTimeout(240_000);
  await openTopicStage(page);
  await expect(page.getByTestId("card-RE2E-1")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("approve-RE2E-1").click();
  await expect(page.getByTestId("card-RE2E-1")).toBeHidden({ timeout: 20_000 });

  // adversarial divergence AFTER approval: the live slot body changes; the approved pin does not
  execSync(
    "docker exec -w /work tanaghom-gateapi python -c \"import sys; sys.path.insert(0,'gates'); " +
    "import engine; c=engine.db_connect(); cur=c.cursor(); " +
    "cur.execute(\\\"UPDATE slot SET topic_angle='زاوية معدلة بعد الاعتماد' WHERE slot_id='RE2E-1'\\\"); " +
    "c.commit()\"", { stdio: "ignore" });

  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("trail-inspect-toggle-RE2E-1").click();
  const panel = page.getByTestId("trail-inspect-RE2E-1");
  await expect(panel).toBeVisible();

  // the APPROVED revision's body is still shown as the topic definition…
  await expect(page.getByTestId("trail-inspect-topic-body-RE2E-1")).toContainText("الزاوية الأصلية للذات");
  // …AND the diverged live slot body is shown alongside it, truthfully labeled
  const slotBody = page.getByTestId("trail-inspect-slot-body-RE2E-1");
  await expect(slotBody).toBeVisible();
  await expect(slotBody).toContainText("زاوية معدلة بعد الاعتماد");
  await expect(slotBody).toContainText(/differs from the approved revision/i);
});

// #237 review P2 — script-stage approval-transition parity: the SAME persisted script definition
// the active card revealed (body/beats, delivery direction, final line, #154 model attribution)
// stays inspectable after approval, read-only, including at mobile width. Uses the RSCR script
// round (real script rows + registry structure + persisted provider:model label).
test("script-stage approval keeps the full script definition inspectable, read-only (#237)", async ({ page }) => {
  test.setTimeout(240_000);
  reseedScriptRound();
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RSCR").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-script").click();

  // pre-approval baseline: the ACTIVE card reveals the persisted script definition
  const card = page.getByTestId("card-RSCR-2");
  await expect(card).toBeVisible({ timeout: 20_000 });
  await card.getByText("show script", { exact: true }).click();
  await expect(card).toContainText("نص السكربت الثاني");
  const finalLine = "إذا لسه في صدق، في باب ينفتح قبل ما ينغلق كل شيء.";

  // approval transition
  await page.getByTestId("approve-RSCR-2").click();
  await expect(card).toBeHidden({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });

  // post-approval: the trail opens to the same definition
  await page.getByTestId("trail-inspect-toggle-RSCR-2").click();
  const panel = page.getByTestId("trail-inspect-RSCR-2");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("الانفصال الصامت");            // registry-structured beat content
  await expect(panel).toContainText(finalLine);                     // final line
  await expect(panel).toContainText("ابدأ بنبرة حزينة");            // delivery direction
  const attribution = page.getByTestId("trail-inspect-attribution-RSCR-2");
  await expect(attribution).toContainText("groq:llama-e2e");        // persisted model, verbatim (#154)
  await expect(attribution).toContainText(/approved/);              // the PINNED approved revision

  // strictly read-only, and detail survives narrowing to mobile
  const btns = panel.locator("button");
  for (let i = 0; i < (await btns.count()); i++) {
    expect(await btns.nth(i).getAttribute("data-testid")).toMatch(/^trail-inspect-/);
  }
  await expect(panel.locator("textarea, input, select")).toHaveCount(0);
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(panel).toBeVisible();
  await expect(attribution).toBeVisible();
});
