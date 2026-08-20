import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #449 — bounded browser evidence for the V2 final-review sign-off action surface.
//
// WHAT THIS PROVES, AND WHY IT IS SHAPED THIS WAY.
//
// An ELIGIBLE target needs a seeded, admitted, fully-pinned final-review package. Seeding is outside
// this directive, so the eligible-path submit is deliberately fixture-gated and SKIPS without the
// fixture. Per the Codex Q7 evidence rule a skipped case is a DECLARED EVIDENCE GAP, never a pass —
// so the cases that carry the real weight here are the ones that need NO fixture and are
// deterministic:
//
//   1. the /gw write boundary admits this exact path and forwards the canonical typed code VERBATIM,
//      while WRITING NOTHING (`engine.sign_off` step 1 raises `signoff_target_unavailable` before any
//      idempotency lookup, receipt insert, or audit — the refusal happens on a pure SELECT);
//   2. the boundary was widened by exactly ONE exact-match entry, not by a prefix;
//   3. the surface fails closed for a target the server does not admit — no submit control exists;
//   4. the preflight surface offers NO entry affordance for an ineligible target;
//   5. nothing rendered implies authorization.
//
// Cases 3–5 need only the unsigned preflight READ, which fails closed for an unknown gate, so they
// are fixture-free by construction. Cases 1–2 additionally need the write runtime
// (`TANAGHOM_DEV_MODE`), because /gw refuses to sign at all outside an explicit local/dev/test
// runtime — a 501 there is a RUNTIME POSTURE, not a boundary result, and this spec reports the mode
// explicitly rather than letting a 501 masquerade as a passing boundary check.

/** A well-formed UUID that is deliberately NOT a real gate. Canonical lowercase, so it passes the
 *  server's `_signoff_canonical_uuid` and reaches the command's own target lookup. */
const UNKNOWN_GATE = "00000000-0000-4000-8000-000000000000";
const UNKNOWN_SLOT = "E2E-NO-SUCH-SLOT";

/** The exact canonical request body. Four binding fields + an opaque key, and nothing else. */
const BODY = {
  snapshot_id: "00000000-0000-4000-8000-000000000001",
  topic_revision: 1,
  script_revision: 1,
  workflow_version_id: "00000000-0000-4000-8000-000000000002",
  idempotency_key: "e2e-probe",
};

/** A seeded eligible target, supplied out of band. Absent -> the eligible path is a declared gap. */
const ELIGIBLE_GATE = process.env.SIGNOFF_ELIGIBLE_GATE;
const ELIGIBLE_SLOT = process.env.SIGNOFF_ELIGIBLE_SLOT;

const signOffUrl = (gate: string, slot: string) =>
  `${WB_URL}/gw/gates/${encodeURIComponent(gate)}/slots/${encodeURIComponent(slot)}/sign-off`;

/**
 * Is the gate API reachable THROUGH the workbench seam?
 *
 * The presentation cases below assert on a typed preflight READ, so they need the upstream API — not
 * a fixture, but a live backend. When it is absent the seam truthfully returns 503 and those cases
 * would fail for an environmental reason rather than a product one. They therefore declare the
 * dependency and SKIP with a named reason, which is reported as an evidence gap — never as a pass.
 *
 * This guard is deliberately narrow: it keys on TRANSPORT reachability only (`/gw/health`, an
 * existing allowlisted read), so it can never mask a product failure while the backend is up.
 */
async function gateApiReachable(request: import("@playwright/test").APIRequestContext): Promise<boolean> {
  try {
    const res = await request.get(`${WB_URL}/gw/health`);
    return res.status() === 200;
  } catch {
    return false;
  }
}

test.describe("#449 V2 sign-off action — write boundary", () => {
  // Split deliberately: ADMISSION into the write boundary is provable with no backend at all, while
  // "the command was reached and answered" needs the gate API. Keeping them in one case would make
  // the provable half unrunnable whenever the backend is absent.
  test("the seam ADMITS the sign-off path into the write boundary", async ({ request }) => {
    const res = await request.post(signOffUrl(UNKNOWN_GATE, UNKNOWN_SLOT), { data: BODY });

    // Runtime posture, reported rather than hidden: outside an explicit dev/test runtime /gw refuses
    // to sign before the allowlist is ever consulted, so this case cannot prove admission.
    test.skip(res.status() === 501,
      "write runtime absent (TANAGHOM_DEV_MODE unset): /gw refuses to sign before the allowlist is consulted");

    // The decisive assertion: NOT the seam's own boundary refusal. The allowlist admitted this exact
    // path and the seam went on to attempt the upstream request — which is what admission MEANS.
    expect(res.status(), "the sign-off path must be inside the write boundary").not.toBe(403);
    expect(await res.text(), "the seam must not refuse this path at its boundary")
      .not.toContain("not in the workbench write boundary");
  });

  test("the command is reached and the canonical code arrives verbatim (writes nothing)", async ({ request }) => {
    test.skip(!(await gateApiReachable(request)),
      "gate API unreachable through the workbench seam: this case asserts on the command's own answer");
    const res = await request.post(signOffUrl(UNKNOWN_GATE, UNKNOWN_SLOT), { data: BODY });
    test.skip(res.status() === 501, "write runtime absent (TANAGHOM_DEV_MODE unset)");

    // The command was reached and refused on its own terms, with the canonical code intact. This
    // writes nothing: `engine.sign_off` step 1 raises before any idempotency lookup, receipt insert,
    // or audit — the refusal happens on a pure SELECT.
    expect(res.status()).toBe(404);
    const body = await res.json();
    const code = body?.detail?.error ?? body?.error;
    expect(code, "the canonical typed code must arrive verbatim").toBe("signoff_target_unavailable");
  });

  test("the boundary was widened by exactly ONE exact-match entry, not a prefix", async ({ request }) => {
    // A sibling verb under the same prefix, a shorter path, and a longer path are all still refused —
    // proving `resolveAllowedWritePath` matches the exact 5 segments rather than "POST under /gates".
    for (const path of [
      `/gw/gates/${UNKNOWN_GATE}/slots/${UNKNOWN_SLOT}/sign-off-please`,
      `/gw/gates/${UNKNOWN_GATE}/sign-off`,
      `/gw/gates/${UNKNOWN_GATE}/slots/${UNKNOWN_SLOT}/sign-off/extra`,
    ]) {
      const res = await request.post(`${WB_URL}${path}`, { data: BODY });
      test.skip(res.status() === 501, "write runtime absent (TANAGHOM_DEV_MODE unset)");
      expect(res.status(), `${path} must stay outside the write boundary`).toBe(403);
      expect(await res.text()).toContain("not in the workbench write boundary");
    }
  });
});

test.describe("#449 V2 sign-off action — fail-closed presentation (fixture-free)", () => {
  test("a target the server does not admit offers NO submit control", async ({ page, request }) => {
    test.skip(!(await gateApiReachable(request)),
      "gate API unreachable through the workbench seam: this case asserts on a typed preflight READ");
    await page.goto(`${WB_URL}/gates/${UNKNOWN_GATE}/slots/${UNKNOWN_SLOT}/sign-off`);
    const panel = page.getByTestId("sign-off-action");
    await expect(panel).toHaveAttribute("data-load", "ok");

    // The server's own verdict drives this — the client re-derives no eligibility.
    await expect(panel).toHaveAttribute("data-attemptable", "false");
    await expect(panel).toHaveAttribute("data-attemptability", "server_not_available");

    // The control does not exist. Not disabled — absent.
    await expect(page.getByTestId("signoff-submit")).toHaveCount(0);
    // Nothing was attempted, so there is no result of any kind.
    await expect(panel).toHaveAttribute("data-result", "none");
    await expect(page.getByTestId("signoff-result")).toHaveCount(0);
    await expect(page.getByTestId("signoff-receipt")).toHaveCount(0);
    // No binding fields are displayed for a target that has no complete server-authored tuple.
    await expect(page.getByTestId("signoff-binding")).toHaveCount(0);
  });

  test("the preflight surface offers NO entry affordance for an ineligible target", async ({ page, request }) => {
    test.skip(!(await gateApiReachable(request)),
      "gate API unreachable through the workbench seam: this case asserts on a typed preflight READ");
    await page.goto(`${WB_URL}/gates/${UNKNOWN_GATE}/slots/${UNKNOWN_SLOT}/approval-preflight`);
    const panel = page.getByTestId("approval-preflight");
    await expect(panel).toHaveAttribute("data-load", "ok");
    await expect(panel).toHaveAttribute("data-available", "false");

    // #449 — the action route is unreachable from here when the server says the target is not
    // available. An ineligible target is never given a reachable action surface.
    await expect(page.getByTestId("apf-signoff-entry")).toHaveCount(0);

    // The merged #447 read-only contract is preserved intact.
    await expect(page.getByTestId("apf-verdict")).toBeVisible();
    await expect(page.getByTestId("apf-tuple")).toBeVisible();
  });

  test("nothing rendered implies authorization (no-authority-inference)", async ({ page, request }) => {
    test.skip(!(await gateApiReachable(request)),
      "gate API unreachable through the workbench seam: this case asserts on a typed preflight READ");
    await page.goto(`${WB_URL}/gates/${UNKNOWN_GATE}/slots/${UNKNOWN_SLOT}/sign-off`);
    await expect(page.getByTestId("sign-off-action")).toHaveAttribute("data-load", "ok");

    // The /gw route signs its OWN principal, so second-person or permission-granting copy would be
    // false in the IAM-off case and unprovable in general. #447/#448 disclose no principal at all.
    const text = ((await page.getByTestId("sign-off-action").textContent()) || "").toLowerCase();
    for (const phrase of [
      "you are", "you can", "you may", "your ", "permission", "permitted",
      "allowed to", "eligible to", "authorized to", "will succeed", "guaranteed",
    ]) {
      expect(text, `sign-off copy must not contain "${phrase}"`).not.toContain(phrase);
    }
    expect(text, 'sign-off copy must not address the operator as "you"').not.toMatch(/\byou\b/);

    // No principal identity is disclosed anywhere, because the server sends none.
    for (const leak of ["principal", "approver", "reviewer_id", "x-principal"]) {
      expect(text, `sign-off copy must not disclose "${leak}"`).not.toContain(leak);
    }
  });
});

test.describe("#449 V2 sign-off action — eligible path (fixture-gated)", () => {
  // DECLARED EVIDENCE GAP when skipped (Codex Q7): an eligible target requires a seeded, admitted,
  // fully-pinned final-review package, and seeding is outside this directive's scope. A skip here is
  // reported as a gap in the completion evidence — never counted as a pass.
  test("an eligible target exposes the entry affordance and the submit control", async ({ page, request }) => {
    test.skip(!(await gateApiReachable(request)), "gate API unreachable through the workbench seam");
    test.skip(!ELIGIBLE_GATE || !ELIGIBLE_SLOT,
      "set SIGNOFF_ELIGIBLE_GATE and SIGNOFF_ELIGIBLE_SLOT to a seeded admitted, fully-pinned final-review target");

    await page.goto(`${WB_URL}/gates/${ELIGIBLE_GATE!}/slots/${ELIGIBLE_SLOT!}/approval-preflight`);
    await expect(page.getByTestId("approval-preflight")).toHaveAttribute("data-available", "true");
    const entry = page.getByTestId("apf-signoff-entry");
    await expect(entry).toBeVisible();
    await entry.click();

    const panel = page.getByTestId("sign-off-action");
    await expect(panel).toHaveAttribute("data-load", "ok");
    await expect(panel).toHaveAttribute("data-attemptable", "true");
    await expect(page.getByTestId("signoff-submit")).toBeVisible();

    // The four binding fields are displayed exactly as the server authored them.
    const binding = page.getByTestId("signoff-binding");
    for (const member of ["snapshot_id", "topic_revision", "script_revision", "workflow_version_id"]) {
      await expect(binding.locator(`[data-member="${member}"]`)).toHaveCount(1);
    }
    // The gate/slot travel in the path, never in the body — they are not binding-field rows.
    await expect(binding.locator('[data-member="gate_id"]')).toHaveCount(0);
    await expect(binding.locator('[data-member="slot_id"]')).toHaveCount(0);
  });
});
