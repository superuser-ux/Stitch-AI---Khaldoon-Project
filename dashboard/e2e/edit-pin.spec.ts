import { test, expect, type Page } from "@playwright/test";
import { execSync } from "node:child_process";
import { reseedOpsRounds } from "./seed-ops";

// #255 S1 — the approved MASTER edit pin: after edit_review approval, the inspection path shows
// the pinned approved master and the CURRENT master distinctly; a newer master version (or a
// platform-variant sibling) never moves the approved display. Read-only — no mutation affordance.
// (gates.selftest §14b proves the atomic/fail-closed/concurrency engine contract; this proves the
// visible truth at desktop and 375px.)

test.beforeEach(() => reseedOpsRounds());

async function openEditFull(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-REDIT").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-edit").click();
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(page.getByTestId("density-full")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("density-full").click();
}

// post-approval divergence through the EXISTING dam path only: a newer master version AND a
// same-revision platform-variant sibling (the adversarial display case).
function divergeMasters() {
  const py = `
import sys
sys.path.insert(0, "gates")
import engine, dam
conn = engine.db_connect()
dam.add_asset(conn, "REDIT-1", "media_edit", "edit", uri="placeholder://edit/REDIT-1-v2", actor="e2e")
dam.add_asset(conn, "REDIT-1", "media_edit", "edit", uri="placeholder://edit/REDIT-1-ig", platform_variant="instagram", actor="e2e")
conn.commit()
print("ok")
`;
  execSync("docker exec -i -w /work tanaghom-gateapi python -", { input: py });
}

test("approved master edit stays pinned and visibly distinct from a newer master (#255)", async ({ page }) => {
  test.setTimeout(240_000);
  await openEditFull(page);

  // attach the master edit (v1) through the existing supported path, then approve
  const card = page.getByTestId("card-REDIT-1");
  await expect(card).toBeVisible({ timeout: 20_000 });
  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://edit/REDIT-1-v1");
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText("placeholder://edit/REDIT-1-v1");
  await page.getByTestId("approve-REDIT-1").click();
  await expect(card).toBeHidden({ timeout: 20_000 });
  await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });

  // pinned == current master right after approval — labeled as such, truthfully
  await page.getByTestId("trail-inspect-toggle-REDIT-1").click();
  const pinLine = page.getByTestId("trail-inspect-approved-edit-REDIT-1");
  await expect(pinLine).toBeVisible({ timeout: 20_000 });
  await expect(pinLine).toContainText(/Approved master edit: v1/);
  await expect(pinLine).toContainText(/this is the current master/);

  // diverge: newer master v2 + adversarial same-revision platform variant
  divergeMasters();
  await page.reload();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("trail-inspect-toggle-REDIT-1").click();
  const pinLine2 = page.getByTestId("trail-inspect-approved-edit-REDIT-1");
  await expect(pinLine2).toBeVisible({ timeout: 20_000 });
  // the approved display did NOT move; drift is explicit; the variant never becomes the master
  await expect(pinLine2).toContainText(/Approved master edit: v1/);
  const drift = page.getByTestId("trail-inspect-edit-drift-REDIT-1");
  await expect(drift).toContainText(/current master is v2/);
  await expect(drift).toContainText(/approved display does not move/i);
  await expect(pinLine2).not.toContainText(/instagram/);

  // read-only: only inspection affordances inside the panel — no mutation controls
  const panel = page.getByTestId("trail-inspect-REDIT-1");
  const btns = panel.locator("button");
  for (let i = 0; i < (await btns.count()); i++) {
    expect(await btns.nth(i).getAttribute("data-testid")).toMatch(/^trail-inspect-/);
  }
  await expect(panel.locator("textarea, input, select")).toHaveCount(0);

  // 375px: the same truthful distinction stays accessible with no document overflow
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByTestId("trail-inspect-approved-edit-REDIT-1")).toBeVisible();
  await expect(page.getByTestId("trail-inspect-edit-drift-REDIT-1")).toBeVisible();
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

// #259 S2 — the governed register-completed-edit action appears on the active Edit card for an
// authorized reviewer, and reports a TRUTHFUL outcome. This dev runtime has no RESOURCESPACE_RW_*
// env, so the server returns 503 "not configured" — the UI must surface that, never fabricate a
// registration or leave a phantom bound state. (sdam_selftest proves the phase-audited state
// machine + both recovery cases; api_selftest proves the 401/503 boundary; this proves the surface.)
// whether the gate API is running with the #259 in-memory SDAM stub (a real run never is)
async function sdamStubOn(request: import("@playwright/test").APIRequestContext): Promise<boolean> {
  try { return Boolean((await (await request.get(`${process.env.API_URL || "http://localhost:8009"}/health`)).json()).sdam_stub); }
  catch { return false; }
}

test("register-completed-edit is a governed action with a truthful unconfigured outcome (#259)", async ({ page, request }) => {
  test.setTimeout(240_000);
  test.skip(await sdamStubOn(request), "stub configures the writer; the unconfigured-503 truth is proven when the stub is OFF");
  await openEditFull(page);

  const card = page.getByTestId("card-REDIT-1");
  await expect(card).toBeVisible({ timeout: 20_000 });

  // not bound yet, and the ONE governed register action is offered on the active edit card
  await expect(page.getByTestId("sdam-notbound-REDIT-1")).toContainText(/not bound/i);
  const register = page.getByTestId("sdam-register-edit-REDIT-1");
  await expect(register).toBeVisible();

  await register.click();
  // truthful outcome on an RS-write-unconfigured runtime — a failure message, never a fake success
  const msg = page.getByTestId("sdam-register-msg-REDIT-1");
  await expect(msg).toBeVisible({ timeout: 20_000 });
  await expect(msg).not.toContainText(/resource \d+/i);   // no fabricated resource id
  // still truthfully not bound afterwards (no phantom binding)
  await expect(page.getByTestId("sdam-notbound-REDIT-1")).toBeVisible();
});

// #259 P1b follow-up — a registered binding whose field-100 discovery projection is pending is a
// SERVER-OBSERVABLE, reload-stable state (derived from audit truth, no live provider read), and it
// carries a governed projection-only retry action on the bound card. Proven at desktop + 375px, and
// proven to CLEAR reload-stably once the projection converges (the convergent path writes field 100).
// (sdam_selftest proves the adapter convergence + read-model derivation; this proves the surface.)
function seedProjectionPending() {
  const py = `
import sys
sys.path.insert(0, "gates")
import engine, sdam
conn = engine.db_connect(); cur = conn.cursor()
cur.execute("SET session_replication_role = replica")
cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN (SELECT binding_id FROM sdam_asset_binding WHERE slot_id = 'REDIT-1')")
cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id = 'REDIT-1'")
cur.execute("SET session_replication_role = DEFAULT")
cur.execute("DELETE FROM audit_log WHERE entity_id='REDIT-1' AND entity='sdam_registration'")
cur.execute("SELECT asset_id::text, version FROM asset WHERE slot_id='REDIT-1' AND stage='media_edit' AND kind='edit' AND platform_variant IS NULL AND status='active' ORDER BY version DESC LIMIT 1")
row = cur.fetchone()
if not row:
    aid = str(__import__("dam", fromlist=["add_asset"]).add_asset(conn, "REDIT-1", "media_edit", "edit", uri="e://redit-master", actor="e2e")); ver = 1
else:
    aid, ver = row
# a registered item ALWAYS has the S1 pin (slot_approval('edit') + the immutable pin event); the
# register endpoint re-checks it, so a realistic projection-pending fixture must include it.
cur.execute("DELETE FROM slot_approval WHERE slot_id='REDIT-1' AND artifact='edit'")
cur.execute("INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind) VALUES ('REDIT-1','edit',%s,'khal','user')", (ver,))
cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) VALUES ('slot','REDIT-1','approved_edit_master_pinned','khal', jsonb_build_object('asset_id', %s::text, 'revision', %s))", (aid, ver))
conn.commit()
bid = str(sdam.create_binding(conn, aid, ver, "REDIT-1", "424242", "e2e"))
# registered audit, NO projection-written audit -> projection_pending True
cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) VALUES ('sdam_registration','REDIT-1','sdam_edit_registered','e2e', jsonb_build_object('binding_id', %s, 'asset_id', %s::text))", (bid, aid))
conn.commit()
print(bid)
`;
  return execSync("docker exec -i -w /work tanaghom-gateapi python -", { input: py }).toString().trim().split("\n").pop()!.trim();
}

function completeProjection(bid: string) {
  const py = `
import sys
sys.path.insert(0, "gates")
import engine
conn = engine.db_connect(); cur = conn.cursor()
cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) VALUES ('sdam_registration','REDIT-1','sdam_edit_projection_written','e2e', jsonb_build_object('binding_id', %s))", ("${bid}",))
conn.commit(); print("ok")
`;
  execSync("docker exec -i -w /work tanaghom-gateapi python -", { input: py });
}

for (const width of [1280, 375]) {
  test(`projection-pending binding shows a governed retry action and clears reload-stably at ${width}px (#259)`, async ({ page }) => {
    test.setTimeout(240_000);
    const bid = seedProjectionPending();
    await openEditFull(page);
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });

    // the pending truth is rendered (server-derived, survives this fresh load) with a retry action
    const pending = page.getByTestId(`sdam-projection-pending-${bid}`);
    await expect(pending).toBeVisible({ timeout: 20_000 });
    await expect(pending).toContainText(/projection pending/i);
    const retry = page.getByTestId(`sdam-projection-retry-${bid}`);
    await expect(retry).toBeVisible();
    // no document overflow at this width with the pending banner + action present
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);

    // the pending state is RELOAD-stable (not transient client state): reload, still pending
    await page.reload();
    await page.waitForLoadState("networkidle");
    if (await page.getByTestId("open-gate").isVisible().catch(() => false)) await page.getByTestId("open-gate").click();
    await page.getByTestId("density-full").click();
    await expect(page.getByTestId(`sdam-projection-pending-${bid}`)).toBeVisible({ timeout: 20_000 });

    // once the projection converges server-side (the projection-only path), the pending truth
    // CLEARS reload-stably — no phantom, no second resource/binding involved
    completeProjection(bid);
    await page.reload();
    await page.waitForLoadState("networkidle");
    if (await page.getByTestId("open-gate").isVisible().catch(() => false)) await page.getByTestId("open-gate").click();
    await page.getByTestId("density-full").click();
    await expect(page.getByTestId(`sdam-projection-pending-${bid}`)).toHaveCount(0);
  });
}

// #259 P1b follow-up (Codex) — the GOVERNED RETRY, driven by a real UI click against the in-memory
// SDAM stub. Proves: clicking the retry action invokes POST /slots/{id}/sdam/register-edit, receives
// the typed convergent outcome (Phase D only), and the pending state CLEARS on reload — with exactly
// one binding/resource, no duplicate. Runs only when the gate API has TANAGHOM_SDAM_STUB on.
function bindingCount(): number {
  const py = `
import sys
sys.path.insert(0, "gates")
import engine
c = engine.db_connect(); cur = c.cursor()
cur.execute("SELECT count(*) FROM sdam_asset_binding WHERE slot_id='REDIT-1'")
print(cur.fetchone()[0])
`;
  return Number(execSync("docker exec -i -w /work tanaghom-gateapi python -", { input: py }).toString().trim().split("\n").pop());
}

for (const width of [1280, 375]) {
  test(`governed projection retry click converges Phase-D-only and clears pending at ${width}px (#259)`, async ({ page, request }) => {
    test.setTimeout(240_000);
    test.skip(!(await sdamStubOn(request)), "requires the gate API in-memory SDAM stub (TANAGHOM_SDAM_STUB)");
    const bid = seedProjectionPending();
    const before = bindingCount();
    await openEditFull(page);
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });

    // the pending action is visible; CLICK it (the real governed action, not a DB shortcut).
    // #261 repaired the shell (sticky display chrome is now pointer-transparent + scroll-padding
    // budget), so the governed action takes an ORDINARY pointer click() at every viewport — no
    // dispatchEvent/force/coordinate bypass.
    const retry = page.getByTestId(`sdam-projection-retry-${bid}`);
    await expect(retry).toBeVisible({ timeout: 20_000 });
    await retry.scrollIntoViewIfNeeded();
    await retry.click();

    // the pending truth clears reload-stably — the click drove the endpoint to convergence
    await expect(page.getByTestId(`sdam-projection-pending-${bid}`)).toHaveCount(0, { timeout: 20_000 });
    await page.reload();
    await page.waitForLoadState("networkidle");
    if (await page.getByTestId("open-gate").isVisible().catch(() => false)) await page.getByTestId("open-gate").click();
    await page.getByTestId("density-full").click();
    await expect(page.getByTestId(`sdam-projection-pending-${bid}`)).toHaveCount(0);

    // Phase D only: exactly the same one binding, no duplicate created by the retry
    expect(bindingCount()).toBe(before);
    expect(before).toBe(1);
  });
}

// #259 P1 (Codex) — a NORMAL single-item Edit approval closes/advances the gate and moves the item
// into the durable advanced trail. The governed S2 register affordance must stay reachable THERE
// (it's exactly when the S1 pin makes registration eligible). Proven with a real post-approval flow:
// approve the master edit, confirm it advanced into the trail, then invoke the register action from
// the trail and see the truthful outcome — at desktop and 375px. Runs with the SDAM stub so the
// governed action converges end-to-end.
for (const width of [1280, 375]) {
  test(`advanced-trail Edit item exposes and invokes the governed register action at ${width}px (#259)`, async ({ page, request }) => {
    test.setTimeout(240_000);
    test.skip(!(await sdamStubOn(request)), "requires the gate API in-memory SDAM stub (TANAGHOM_SDAM_STUB)");
    await openEditFull(page);

    // attach the master edit and approve it — a normal single-item approval closes/advances the gate
    const card = page.getByTestId("card-REDIT-1");
    await expect(card).toBeVisible({ timeout: 20_000 });
    await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://edit/REDIT-1-master");
    await card.getByRole("button", { name: /add media/i }).click();
    await expect(card).toContainText("placeholder://edit/REDIT-1-master");
    await page.getByTestId("approve-REDIT-1").click();
    await expect(card).toBeHidden({ timeout: 20_000 });

    // it has advanced into the durable trail — the register affordance is present HERE
    await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
    await page.setViewportSize({ width, height: width === 375 ? 812 : 900 });
    const register = page.getByTestId("sdam-register-edit-REDIT-1");
    await expect(register).toBeVisible({ timeout: 20_000 });

    // invoke it with an ORDINARY click on the repaired shell — it registers (Pending in SDAM)
    await register.scrollIntoViewIfNeeded();
    await register.click();
    const msg = page.getByTestId("sdam-register-msg-REDIT-1");
    await expect(msg).toBeVisible({ timeout: 20_000 });
    await expect(msg).toContainText(/Registered — resource/i);
    // the persisted binding now shows on the trail row (truthful state, reload-independent)
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("advanced-trail")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("sdam-readiness-REDIT-1")).not.toContainText(/not bound/i);
  });
}
