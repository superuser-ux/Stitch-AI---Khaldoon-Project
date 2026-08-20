import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";
import { resolveAllowedWritePath, resolveAllowedQuery } from "../lib/api-contract";

// #367 — the governed Script review LIFECYCLE surface.
//
// WHAT THESE GUARD. The engine lifecycle is artifact-generic; this slice exposes it in V2 without
// letting the surface invent authority or silently fall back to Topic state. Three regressions would
// each look correct on screen:
//   1. The write boundary could quietly stop admitting the recovery/undo transitions (reopen/undecide)
//      the lifecycle needs — or, worse, admit them for the wrong path shape.
//   2. The per-item read could drop `artifact=script` and be answered with TOPIC state (topic_item and
//      revisions BOTH default to topic upstream). A Script surface reading topic history is the exact
//      cross-artifact fallback the slice forbids.
//   3. V2 could decide availability itself instead of PROJECTING the server's typed action map — a
//      surface that re-derived eligibility could offer an action the command will refuse.
//
// The boundary assertions run in-process against the pure allowlist functions (admission is decidable
// with no request and no side effect); the render assertions mock the typed action map and assert the
// controls are exactly what the server described.

const ROUND = "RSL367E";
const SLOT = `${ROUND}-1`;

test.describe("#367 write/read boundary admits the Script lifecycle, refuses the wrong shape", () => {
  test("reopen and undecide are enumerated writes; nothing broader is", () => {
    expect(resolveAllowedWritePath(["slots", SLOT, "reopen"])).not.toBeNull();
    expect(resolveAllowedWritePath(["gates", "11111111-2222-3333-4444-555555555555", "undecide"]))
      .not.toBeNull();
    // still not a general proxy
    expect(resolveAllowedWritePath(["slots", SLOT, "delete"])).toBeNull();
    expect(resolveAllowedWritePath(["slots", SLOT, "reopen", "x"])).toBeNull();
  });

  test("topic_item admits artifact=script, keeps the topic default, refuses a script->topic fallback", () => {
    const p = ["slots", SLOT, "topic_item"];
    expect(resolveAllowedQuery(p, new URLSearchParams("artifact=script"))).toBe("artifact=script");
    // absent artifact keeps the EXISTING topic-workbench default (empty allowed query)
    expect(resolveAllowedQuery(p, new URLSearchParams(""))).toBe("");
    // a non-script artifact must be refused — never a silent topic answer for a script read
    expect(resolveAllowedQuery(p, new URLSearchParams("artifact=topic"))).toBeNull();
    expect(resolveAllowedQuery(p, new URLSearchParams("artifact=script&artifact=topic"))).toBeNull();
    // revisions still REQUIRES artifact=script (its topic default is dangerous)
    expect(resolveAllowedQuery(["slots", SLOT, "revisions"], new URLSearchParams(""))).toBeNull();
  });
});

async function withRun(page: import("@playwright/test").Page, actions: Record<string, unknown>) {
  await page.route("**/gw/workflow-stages/active-enabled", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ version_id: "wfv-367", version_no: 1, status: "active",
      stages: [{ stage_key: "script_review", stage_label: "Scripts", stage_group: "Content", ordinal: 1,
                 enabled: true, gate_stage: "script_review", stage_kind: "transition",
                 generator_kind: "ai", writer_mode: "scripts", generates_from: "TOPIC_APPROVED",
                 approve_to: null }] }),
  }));
  await page.route(`**/gw/rounds/${ROUND}`, (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ round_id: ROUND, label: "sl367", slots: [{ slot_id: SLOT, status: "DRAFT_ASSIGNED" }] }),
  }));
  await page.route("**/stages/script_review/action", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ action: "script_generate", available: false, reason_code: "attempt_already_completed",
      detail: null, input_revisions: [] }),
  }));
  await page.route("**/stages/script_review/state", (r) => r.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ next_action: "complete", state: "complete" }),
  }));
  // the per-item read the lifecycle controls PROJECT — must be requested with artifact=script
  await page.route(`**/gw/slots/${SLOT}/topic_item**`, (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ slot_id: SLOT, artifact: "script", status: "DRAFT_ASSIGNED",
      head_revision: 2, approved_revision: null, downstream_advanced: false, revisions: [], actions }),
  }));
  await page.route(`**/gw/slots/${SLOT}/revisions**`, (r) => r.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify([]),
  }));
}

test("lifecycle controls are PROJECTED from the server's typed action map (allowed + denied)", async ({ page }) => {
  await withRun(page, {
    inspect: { allowed: true }, history: { allowed: true },
    approve: { allowed: true }, edit: { allowed: true }, request_change: { allowed: true },
    rework: { allowed: true },
    drop: { allowed: true },
    reopen: { allowed: false, reason: "nothing_to_reverse" },
  });
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();

  const actions = page.getByTestId(`scripts-actions-${SLOT}`);
  await expect(actions).toHaveAttribute("data-head", "2");
  // no-input controls are offered directly
  await expect(page.getByTestId(`scripts-action-approve-${SLOT}`)).toBeEnabled();
  await expect(page.getByTestId(`scripts-action-drop-${SLOT}`)).toBeEnabled();
  // text-input controls are present but GATED until the reviewer supplies a value (no blanks/placeholders)
  await expect(page.getByTestId(`scripts-action-edit-${SLOT}`)).toBeDisabled();
  await expect(page.getByTestId(`scripts-action-rework-${SLOT}`)).toBeDisabled();
  await expect(page.getByTestId(`scripts-action-request_change-${SLOT}`)).toBeDisabled();
  // a denied action shows the machine reason verbatim, never a bare hide
  await expect(page.getByTestId(`scripts-action-reopen-denied-${SLOT}`))
    .toContainText("nothing_to_reverse");
});

test("active Script rework is PROJECTED as a typed rework_active denial (finding 2)", async ({ page }) => {
  await withRun(page, {
    approve: { allowed: false, reason: "rework_active" },
    edit: { allowed: false, reason: "rework_active" },
    request_change: { allowed: false, reason: "rework_active" },
    rework: { allowed: false, reason: "rework_active" },
    drop: { allowed: false, reason: "rework_active" },
    reopen: { allowed: false, reason: "rework_active" },
  });
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();
  // every mutation is projected as denied with the rework_active reason — the surface never offers an
  // action the guard will refuse while a durable Script rework owns the item.
  for (const n of ["edit", "approve", "drop", "rework", "request_change"]) {
    await expect(page.getByTestId(`scripts-action-${n}-denied-${SLOT}`)).toContainText("rework_active");
  }
});

// SUCCESS-PATH (finding 3/4): the writes carry the CORRECT contract — real reviewer values, the
// `comment` field (not `reason`), and a fresh idempotency key minted at submit — with artifact=script.
async function captureWrite(page: import("@playwright/test").Page, seg: string) {
  const seen: { body?: Record<string, unknown> } = {};
  await page.route(`**/gw/slots/${SLOT}/${seg}`, (r) => {
    seen.body = JSON.parse(r.request().postData() ?? "{}");
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  return seen;
}

test("edit submits the reviewer's explicit value, artifact=script, key minted at submit", async ({ page }) => {
  await withRun(page, { edit: { allowed: true } });
  const seen = await captureWrite(page, "edit");
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();
  await expect(page.getByTestId(`scripts-action-edit-${SLOT}`)).toBeDisabled();   // blank -> gated
  await page.getByTestId(`scripts-edit-value-${SLOT}`).fill("سطر مُراجَع");
  await page.getByTestId(`scripts-action-edit-${SLOT}`).click();
  await expect.poll(() => seen.body?.field).toBe("final_line");
  expect(seen.body?.value).toBe("سطر مُراجَع");            // the explicit value, never blank
  expect(seen.body?.artifact).toBe("script");
  expect(typeof seen.body?.idempotency_key).toBe("string");
  expect((seen.body?.idempotency_key as string).length).toBeGreaterThan(8);
});

test("request-change submits `comment` (not `reason`), artifact=script", async ({ page }) => {
  await withRun(page, { request_change: { allowed: true } });
  const seen = await captureWrite(page, "request_change");
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();
  await page.getByTestId(`scripts-rc-comment-${SLOT}`).fill("tighten the hook");
  await page.getByTestId(`scripts-action-request_change-${SLOT}`).click();
  await expect.poll(() => seen.body?.comment).toBe("tighten the hook");
  expect(seen.body?.reason).toBeUndefined();               // the 422-causing wrong field is gone
  expect(seen.body?.artifact).toBe("script");
});

test("rework submits the reviewer directive + a fresh key, artifact=script", async ({ page }) => {
  await withRun(page, { rework: { allowed: true } });
  const seen = await captureWrite(page, "rework_from");
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();
  await page.getByTestId(`scripts-rework-comment-${SLOT}`).fill("punchier open");
  await page.getByTestId(`scripts-action-rework-${SLOT}`).click();
  await expect.poll(() => seen.body?.comment).toBe("punchier open");
  expect(seen.body?.revision).toBe(2);
  expect(seen.body?.artifact).toBe("script");
  expect(typeof seen.body?.idempotency_key).toBe("string");
});

test("idempotency key CONVERGES across same-payload retries, ROTATES on change/success", async ({ page }) => {
  await withRun(page, { edit: { allowed: true } });
  const keys: string[] = [];
  // an ambiguous failure (500) so the reviewer retries the SAME payload
  let failNext = true;
  await page.route(`**/gw/slots/${SLOT}/edit`, (r) => {
    keys.push(JSON.parse(r.request().postData() ?? "{}").idempotency_key as string);
    if (failNext) { failNext = false; return r.fulfill({ status: 500, contentType: "application/json",
      body: JSON.stringify({ detail: "upstream timeout" }) }); }
    return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();
  await page.getByTestId(`scripts-edit-value-${SLOT}`).fill("same value");
  await page.getByTestId(`scripts-action-edit-${SLOT}`).click();   // fails
  await expect.poll(() => keys.length).toBe(1);
  await page.getByTestId(`scripts-action-edit-${SLOT}`).click();   // RETRY same payload -> succeeds
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);                                   // SAME key: the retry converges

  // after a KNOWN SUCCESS the key rotates; and a CHANGED payload also starts a new identity
  await page.getByTestId(`scripts-edit-value-${SLOT}`).fill("changed value");
  await page.getByTestId(`scripts-action-edit-${SLOT}`).click();
  await expect.poll(() => keys.length).toBe(3);
  expect(keys[2]).not.toBe(keys[1]);                              // NEW key: success + change rotated it
});

test("a governed write refusal is relayed verbatim, never restated as a friendly guess", async ({ page }) => {
  await withRun(page, { drop: { allowed: true } });
  await page.route(`**/gw/slots/${SLOT}/drop`, (r) => r.fulfill({
    status: 409, contentType: "application/json",
    body: JSON.stringify({ detail: { error: "governed_denial", reason: "approved_or_downstream" } }),
  }));
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=script_review`);
  await page.getByTestId(`scripts-slot-toggle-${SLOT}`).click();
  await page.getByTestId(`scripts-action-drop-${SLOT}`).click();
  await expect(page.getByTestId(`scripts-action-refusal-${SLOT}`)).toContainText("approved_or_downstream");
});
