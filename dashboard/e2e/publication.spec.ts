import { test, expect, type Page } from "@playwright/test";
import { execSync } from "node:child_process";
import { reseedOpsRounds } from "./seed-ops";

// #200 (pub.v1) — governed manual publication recording on the distribution stage.
// Proves the SURFACE truth (selftest §18 proves the module, api_selftest the endpoints):
//  * an approved distribution item offers "Record a publication" with registry platforms only
//  * the recorded truth survives reload (server-derived, never client acknowledgment)
//  * a signed-but-unauthorized persona is refused by the SERVER and the UI stays truthful
//  * the affordance exists only on the distribution stage.

function runSql(sql: string) {
  execSync(`docker exec -i tanaghom-db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`,
    { input: sql, stdio: ["pipe", "ignore", "ignore"] });
}

// publication rows hold NO ACTION FKs onto slots/gates/assets, so they MUST be purged BEFORE any
// seed teardown deletes those rows — otherwise every later reseed in the suite would fail. This
// runs first in beforeEach and again in afterAll so no publication row ever outlives this spec.
// The whole purge is ONE transaction: the guard-trigger DISABLE/ENABLE and the deletes commit or
// roll back together, so a mid-purge failure can never leave the triggers disabled.
function purgePublications() {
  runSql(`BEGIN;
          ALTER TABLE publication_event DISABLE TRIGGER trg_publication_event_immutable;
          ALTER TABLE publication DISABLE TRIGGER trg_publication_frozen;
          ALTER TABLE publication_raw_asset DISABLE TRIGGER trg_publication_raw_asset_frozen;
          DELETE FROM publication_raw_asset WHERE publication_intent_id IN
            (SELECT publication_intent_id FROM publication WHERE slot_id LIKE 'RDIST-%');
          DELETE FROM publication_event WHERE publication_intent_id IN
            (SELECT publication_intent_id FROM publication WHERE slot_id LIKE 'RDIST-%');
          DELETE FROM publication WHERE slot_id LIKE 'RDIST-%';
          ALTER TABLE publication_raw_asset ENABLE TRIGGER trg_publication_raw_asset_frozen;
          ALTER TABLE publication ENABLE TRIGGER trg_publication_frozen;
          ALTER TABLE publication_event ENABLE TRIGGER trg_publication_event_immutable;
          DELETE FROM audit_log WHERE entity='publication' AND entity_id LIKE 'RDIST-%';
          COMMIT;`);
}

// The RDIST fixture starts at EDITED (no earlier gates), but pub.v1 eligibility requires the FULL
// committed chain. Grant the upstream production/edit approvals the seed round skips.
function grantUpstreamApprovals() {
  runSql(`DO $$
  DECLARE gid uuid; sid text; st text;
  BEGIN
    FOREACH sid IN ARRAY ARRAY['RDIST-1','RDIST-2'] LOOP
      FOREACH st IN ARRAY ARRAY['production_review','edit_review'] LOOP
        INSERT INTO gate (scope, stage, policy, rule_key, quorum, status)
        VALUES ('batch', st, 'fixed', 'any', '1', 'approved') RETURNING gate_id INTO gid;
        INSERT INTO gate_target (gate_id, slot_id) VALUES (gid, sid);
        INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision)
        VALUES (gid, sid, 'khal', 'approve');
      END LOOP;
    END LOOP;
  END $$;`);
}

test.beforeEach(() => {
  purgePublications();
  reseedOpsRounds();
  grantUpstreamApprovals();
});
test.afterAll(() => purgePublications());

async function openDistribution(page: Page) {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RDIST").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-distribution").click();
  const open = page.getByTestId("open-gate");
  const density = page.getByTestId("density-full");
  await expect.poll(async () => {
    return (await open.isVisible().catch(() => false)) || (await density.isVisible().catch(() => false));
  }, { timeout: 15_000 }).toBe(true);
  if (await open.isVisible().catch(() => false)) await open.click();
  await expect(density).toBeVisible();
  await density.click();
}

async function approveAtDistribution(page: Page, slot: string) {
  const card = page.getByTestId(`card-${slot}`);
  await expect(card).toBeVisible({ timeout: 20_000 });
  await card.getByPlaceholder("media reference (path or URL)").fill(`placeholder://post/${slot}-v1`);
  await card.getByRole("button", { name: /add media/i }).click();
  await expect(card).toContainText(`placeholder://post/${slot}-v1`);
  await page.getByTestId(`approve-${slot}`).click();
  await expect(page.getByTestId(`advanced-item-${slot}`)).toBeVisible({ timeout: 20_000 });
}

test("an approved distribution item records a manual publication that survives reload (#200)", async ({ page }) => {
  test.setTimeout(180_000);
  await openDistribution(page);
  // eligibility requires the RESOLVED distribution gate (#200 B1: an approve decision on a
  // still-open gate is not committed truth), so complete the whole batch before recording
  await approveAtDistribution(page, "RDIST-1");
  await approveAtDistribution(page, "RDIST-2");

  // truthfully unrecorded until the operator says otherwise
  const state = page.getByTestId("publication-state-RDIST-1");
  await expect(state).toContainText("Not recorded as published yet");

  // record: platform choices come from the platform registry (server vocabulary, not hardcoded)
  await page.getByTestId("record-publication-RDIST-1").click();
  await page.getByTestId("publication-platform-RDIST-1").click();
  const options = page.getByRole("option");
  await expect(options.filter({ hasText: /instagram/i })).toHaveCount(1);
  await options.filter({ hasText: /instagram/i }).click();
  await page.getByTestId("publication-url-RDIST-1").fill("https://example.com/p/rdist-1");
  await page.getByTestId("publication-submit-RDIST-1").click();

  // the recorded truth shows durably: state, platform, link, and who attested
  await expect(state).toContainText(/Published — instagram/i, { timeout: 20_000 });
  await expect(state).toContainText("recorded by khal");

  // reload — server-derived, so the record survives (never a client-side acknowledgment)
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("publication-state-RDIST-1")).toContainText(/Published — instagram/i, { timeout: 20_000 });
});

test("the recording affordance is scoped to the distribution stage only (#200)", async ({ page }) => {
  test.setTimeout(120_000);
  // production stage: approve an item so ITS advanced trail exists — no publication affordance there
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RPROD").click();
  await page.waitForLoadState("networkidle");
  await page.getByTestId("nav-production").click();
  const open = page.getByTestId("open-gate");
  if (await open.isVisible().catch(() => false)) await open.click();
  const card = page.getByTestId("card-RPROD-1");
  await expect(card).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("density-full").click();
  await card.getByPlaceholder("media reference (path or URL)").fill("placeholder://raw/RPROD-1-v9");
  await card.getByRole("button", { name: /add media/i }).click();
  await page.getByTestId("approve-RPROD-1").click();
  await expect(page.getByTestId("advanced-item-RPROD-1")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("publication-record-RPROD-1")).toHaveCount(0);
});

// #212 — HTTP-safe idempotency keys. crypto.randomUUID() is SECURE-CONTEXT-ONLY, so on the
// accepted plain-HTTP public-IP internal-review surface the recording dialog threw at open
// (#211; localhost e2e masked it because localhost IS a secure context). These proofs run the
// REAL dialog under the non-secure-context equivalent (randomUUID removed, getRandomValues
// preserved) and pin the key contract: standards-valid unpredictable UUIDv4, ONE key per
// intended submission, no duplicate/partial publication state, and a visible no-request
// failure when no cryptographic source exists at all.
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test.describe("#212 — HTTP-safe publication idempotency keys", () => {
  test("pure logic: both mint paths emit RFC 4122 v4 bits and unique keys; no source fails closed", async () => {
    const { mintOperationKey } = await import("../lib/publication-key");
    const native = Array.from({ length: 200 }, () => mintOperationKey());
    for (const k of native) expect(k).toMatch(UUID_V4);
    expect(new Set(native).size).toBe(200);
    const real = Object.getOwnPropertyDescriptor(globalThis, "crypto")!;
    const realCrypto = globalThis.crypto;
    try {
      // the plain-HTTP browser reality: getRandomValues only
      Object.defineProperty(globalThis, "crypto", {
        configurable: true,
        value: { getRandomValues: (a: Uint8Array) => realCrypto.getRandomValues(a) },
      });
      const fallback = Array.from({ length: 200 }, () => mintOperationKey());
      for (const k of fallback) expect(k).toMatch(UUID_V4);
      expect(new Set(fallback).size).toBe(200);
      // no usable cryptographic source at all -> throws (the dialog turns this into a visible
      // no-request failure, proven in the browser test below)
      Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
      expect(() => mintOperationKey()).toThrow();
    } finally {
      Object.defineProperty(globalThis, "crypto", real);
    }
  });

  test("the dialog works WITHOUT crypto.randomUUID; one intended submission = one v4 key, one publication (#212)", async ({ page }) => {
    test.setTimeout(180_000);
    await page.addInitScript(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (Crypto.prototype as any).randomUUID;
    });
    const createKeys: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/gw\/publications$/.test(req.url())) {
        try { createKeys.push(JSON.parse(req.postData() || "{}").idempotency_key); } catch { /* non-JSON */ }
      }
    });
    await openDistribution(page);
    await approveAtDistribution(page, "RDIST-1");
    await approveAtDistribution(page, "RDIST-2");
    await page.getByTestId("record-publication-RDIST-1").click();
    await page.getByTestId("publication-platform-RDIST-1").click();
    await page.getByRole("option").filter({ hasText: /instagram/i }).click();
    const submitBtn = page.getByTestId("publication-submit-RDIST-1");
    await submitBtn.click();
    await submitBtn.click({ timeout: 1500 }).catch(() => { /* duplicate-interaction pressure */ });
    await expect(page.getByTestId("publication-state-RDIST-1")).toContainText(/Published — instagram/i, { timeout: 20_000 });
    // the key contract: every create request carried the SAME standards-valid v4 key
    expect(createKeys.length).toBeGreaterThanOrEqual(1);
    for (const k of createKeys) expect(k).toMatch(UUID_V4);
    expect(new Set(createKeys).size).toBe(1);
    // server truth survives reload: exactly ONE publication, no duplicate/partial state
    await page.reload();
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("publication-state-RDIST-1")).toHaveCount(1);
    await expect(page.getByTestId("publication-state-RDIST-1")).toContainText(/Published — instagram/i, { timeout: 20_000 });
  });

  test("no usable cryptographic source: visible failure, dialog never opens, ZERO publication requests (#212)", async ({ page }) => {
    test.setTimeout(120_000);
    // fixture-resolve the distribution gate (same pattern as the governance test) so the
    // advanced item exists without walking the approval UI in this failure-path proof
    runSql(`DO $$
    DECLARE gid uuid;
    BEGIN
      SELECT g.gate_id INTO gid FROM gate g JOIN gate_target t ON t.gate_id=g.gate_id
        WHERE g.stage='distribution_review' AND g.status='open' AND t.slot_id='RDIST-1' LIMIT 1;
      IF gid IS NOT NULL THEN
        INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision)
        VALUES (gid, 'RDIST-1', 'khal', 'approve');
        UPDATE gate SET status='approved' WHERE gate_id=gid;
        UPDATE slot SET status='SCHEDULED' WHERE slot_id='RDIST-1';
      END IF;
    END $$;`);
    await page.addInitScript(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (Crypto.prototype as any).randomUUID;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (Crypto.prototype as any).getRandomValues = function () { throw new Error("unavailable"); };
    });
    let publicationPosts = 0;
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/gw\/publications/.test(req.url())) publicationPosts++;
    });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("round-trigger").click();
    await page.getByTestId("round-opt-RDIST").click();
    await page.waitForLoadState("networkidle");
    await page.getByTestId("nav-distribution").click();
    await expect(page.getByTestId("advanced-item-RDIST-1")).toBeVisible({ timeout: 20_000 });
    await page.getByTestId("record-publication-RDIST-1").click();
    // the failure copy is plain operational guidance (#186): truthful no-request statement,
    // actionable next step, and NO implementation/security jargon anywhere on the page
    const failureNote = page.getByTestId("publication-key-unavailable-RDIST-1");
    await expect(failureNote).toBeVisible({ timeout: 10_000 });
    await expect(failureNote).toContainText(/couldn't start in this browser/i);
    await expect(failureNote).toContainText(/nothing was sent/i);
    await expect(failureNote).toContainText(/different browser or contact your administrator/i);
    for (const jargon of [/random/i, /crypto/i, /uuid/i, /secure context/i]) {
      await expect(page.locator("body")).not.toContainText(jargon);
    }
    await expect(page.getByTestId("publication-platform-RDIST-1")).toHaveCount(0);
    expect(publicationPosts).toBe(0);
  });
});

test.describe("server-side governance stays authoritative", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("a signed persona OUTSIDE the publish-gate snapshot is refused by the server (#200)", async ({ page }) => {
    test.setTimeout(180_000);
    // This context enters as nour, who cannot approve at distribution — so the committed
    // distribution approval this test needs is granted directly in the fixture (resolve the open
    // gate as khal), leaving ONLY the recording action to exercise from nour's session.
    runSql(`DO $$
    DECLARE gid uuid;
    BEGIN
      SELECT g.gate_id INTO gid FROM gate g JOIN gate_target t ON t.gate_id=g.gate_id
        WHERE g.stage='distribution_review' AND g.status='open' AND t.slot_id='RDIST-1' LIMIT 1;
      IF gid IS NOT NULL THEN
        INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision)
        VALUES (gid, 'RDIST-1', 'khal', 'approve');
        UPDATE gate SET status='approved' WHERE gate_id=gid;
        UPDATE slot SET status='SCHEDULED' WHERE slot_id='RDIST-1';
      END IF;
    END $$;`);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const entry = page.getByTestId("persona-entry");
    await expect(entry).toBeVisible({ timeout: 20_000 });
    await entry.getByTestId("persona-option-nour").click();
    await page.getByTestId("round-trigger").click();
    await page.getByTestId("round-opt-RDIST").click();
    await page.waitForLoadState("networkidle");
    await page.getByTestId("nav-distribution").click();
    await expect(page.getByTestId("advanced-item-RDIST-1")).toBeVisible({ timeout: 20_000 });

    await page.getByTestId("record-publication-RDIST-1").click();
    await page.getByTestId("publication-platform-RDIST-1").click();
    await page.getByRole("option").filter({ hasText: /instagram/i }).click();
    await page.getByTestId("publication-submit-RDIST-1").click();

    // the SERVER refuses; the UI reports the refusal and never fakes a recorded state
    const toast = page.getByTestId("toast");
    await expect(toast).toBeVisible({ timeout: 20_000 });
    await expect(toast).toHaveAttribute("data-kind", "err");
    await expect(page.getByTestId("publication-state-RDIST-1")).not.toContainText(/Published —/);
  });
});
