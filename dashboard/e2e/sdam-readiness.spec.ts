import { test, expect, type Page } from "@playwright/test";
import { execSync } from "node:child_process";
import { reseedOpsRounds } from "./seed-ops";

// #250 — read-only SDAM readiness + provider-neutral Edit-input visibility on the Production/Edit
// surfaces. Every rendered state must trace to persisted #244 truth or a truthful runtime
// condition; nothing here may claim availability, edit completion, or workflow advancement, and
// nothing here may mutate. (sdam_selftest proves the read model; api_selftest proves the HTTP
// boundary; this proves the surface.)

test.beforeEach(() => reseedOpsRounds());

async function openProductionFull(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RPROD").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-production").click();
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("density-full")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("density-full").click();
}

// seed SDAM truth through the EXISTING sole write paths only (binding + append_observation),
// against the seed round's real production assets — never fabricated in the UI layer.
function bindSdamFixtures() {
  const py = `
import sys
sys.path.insert(0, "gates")
import engine, sdam, dam
conn = engine.db_connect()
aid = dam.add_asset(conn, "RPROD-1", "production", "raw_cut", uri="placeholder://raw/RPROD-1", actor="e2e")
bid = str(sdam.create_binding(conn, aid, 1, "RPROD-1", "70006", "e2e"))
b = sdam.get_binding(conn, bid)
sdam.append_observation(conn, bid, "e2e-ready", "ready", "system", "e2e",
    expected_digest=sdam._digest(sdam.expected_projection(b)),
    observed_digest=sdam._digest(sdam.observed_projection(b, str(b["asset_id"]))))
aid2 = dam.add_asset(conn, "RPROD-2", "production", "raw_cut", uri="placeholder://raw/RPROD-2", actor="e2e")
sdam.create_binding(conn, aid2, 1, "RPROD-2", "70007", "e2e")
conn.commit()
print(bid)
`;
  return execSync("docker exec -i -w /work tanaghom-gateapi python -", { input: py })
    .toString().trim();
}

test("production card shows truthful not-bound SDAM state, read-only, with the #237 inspect link (#250)", async ({ page }) => {
  test.setTimeout(240_000);
  await openProductionFull(page);

  const block = page.getByTestId("sdam-readiness-RPROD-1");
  await expect(block).toBeVisible({ timeout: 20_000 });
  // truthful: nothing is bound yet, and that is exactly what it says — never inferred readiness
  await expect(page.getByTestId("sdam-notbound-RPROD-1")).toContainText(/not bound/i);
  // the approved-content inspection affordance (#237 surface) is present on the production card
  await expect(page.getByTestId("trail-inspect-toggle-RPROD-1")).toBeVisible();
  // read-only: every button in the SDAM block is a read affordance, never a mutation control
  const btns = block.locator("button");
  for (let i = 0; i < (await btns.count()); i++) {
    expect(await btns.nth(i).getAttribute("data-testid")).toMatch(/^(sdam-|trail-inspect-)/);
  }
});

test("bound states render distinctly; fresh-ready exposes the Edit-input summary with truthful unconfigured media (#250)", async ({ page }) => {
  test.setTimeout(240_000);
  const bid = bindSdamFixtures();
  await openProductionFull(page);

  // RPROD-1: fresh ready (persisted observation through the sole write path)
  const ready = page.getByTestId(`sdam-state-${bid}`);
  await expect(ready).toBeVisible({ timeout: 20_000 });
  await expect(ready).toContainText(/fresh ready/i);

  // RPROD-2: bound with NO evidence — visibly distinct from ready AND from provider-pending
  await expect(page.getByTestId("sdam-readiness-RPROD-2")).toContainText(/no readiness evidence yet/i);

  // Edit-input summary from persisted truth only
  await page.getByTestId(`sdam-detail-toggle-${bid}`).click();
  const detail = page.getByTestId(`sdam-detail-${bid}`);
  await expect(detail).toContainText(/Canonical asset/);
  await expect(detail).toContainText("resourcespace:70006");   // provider_key:external_ref, opaque
  await expect(detail).toContainText(/mapping v1/);
  await expect(detail).toContainText(/never advances the workflow/i);

  // media resolution is an EXPLICIT read; this runtime has no RS configuration, so the
  // truthful answer is "not configured" — never a fabricated media source
  await page.getByTestId(`sdam-media-resolve-${bid}`).click();
  await expect(page.getByTestId(`sdam-media-unconfigured-${bid}`)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId(`sdam-media-source-${bid}`)).toHaveCount(0);

  // approval transition: the committed trail row on the production stage keeps the SDAM truth
  await page.getByTestId("approve-RPROD-1").click();
  await expect(page.getByTestId("card-RPROD-1")).toBeHidden({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-item-RPROD-1").getByTestId(`sdam-state-${bid}`))
    .toContainText(/fresh ready/i);

  // still no document-level overflow at mobile width with the SDAM block rendered. Poll (web-first,
  // not a test retry) so a transient post-resize reflow settles deterministically under suite load —
  // measuring the instant after setViewportSize can catch a mid-reflow frame (a flaky +16px).
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByTestId("advanced-item-RPROD-1")).toBeVisible();
  await expect.poll(async () => page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth),
    { timeout: 5000 }).toBeLessThanOrEqual(0);
});
