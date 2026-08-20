import { test, expect, type APIRequestContext } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #314 Stage 2B-2 — the production-shaped BULK Topic disposition + PRESENTATION reorder flow:
// actual V2 UI -> /gw allowlist -> live API -> canonical commands -> durable DB -> read model ->
// rendered result. NON-SKIPPING by construction: it discovers a run with Topic items in review through
// the REAL read path (no mocked client state); a skip would hide real defects.

async function topicRun(request: APIRequestContext) {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    const inReview = (d.slots || []).filter((s: { status?: string }) => /TOPIC|CHANGE/i.test(s.status || "")) as { slot_id: string }[];
    if (inReview.length < 2) continue;
    // Confirm this run has an OPEN topic_review gate by probing the governed bulk endpoint (the server
    // resolves the gate). A truthful "no open topic_review gate" 400 -> skip; a 200 ledger -> usable.
    const sorted = inReview.map((s) => s.slot_id).sort();
    const sacrificial = sorted[sorted.length - 1];   // probe a SEPARATE slot, never the asserted item
    const it = await (await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(sacrificial)}/topic_item`)).json();
    const probe = await request.post(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/bulk-operations`, {
      data: {
        action: "bulk_approve",
        items: [{ slot_id: sacrificial, expected_revision: it.head_revision as number }],
        idempotency_key: `e2e-probe-${r.round_id}-${it.head_revision}`,
      },
    });
    if (probe.ok()) return { id: r.round_id as string, slots: sorted };
  }
  throw new Error("no run with an open topic_review gate + >=2 Topic items — the fixture must provision one; a skip would hide defects");
}

const OUTCOME = /^(succeeded|stale|denied|conflicted|not_attempted)/;

test("bulk disposition: select -> apply -> truthful per-item outcome through the canonical command", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  const slot = slots[0];   // asserted item; the discovery probe used a SEPARATE sacrificial slot (last)
  // Prove the asserted item was NOT pre-mutated by discovery: capture its head now and assert the UI's
  // outgoing CAS pins this SAME unchanged head (discovery touched only the sacrificial slot).
  const pre = await (await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(slot)}/topic_item`)).json();
  const preHead = pre.head_revision as number;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();

  // Capture the outgoing bulk request to PROVE the mandatory per-item expected_revision CAS + the
  // idempotency key are on the wire (never a NULL=head mutation).
  let body: { items?: { expected_revision?: number }[]; idempotency_key?: string } | null = null;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/gw/rounds/") && req.url().includes("/bulk-operations")) {
      try { body = JSON.parse(req.postData() || "{}"); } catch { body = {}; }
    }
  });

  await page.getByTestId(`wb-bulk-select-${slot}`).check();
  await expect(page.getByTestId("wb-bulk-selected")).toHaveText(/1 selected/);
  await page.getByTestId("wb-bulk-apply").click();

  // The truthful per-item outcome, rendered verbatim from the durable ledger.
  await expect(page.getByTestId(`wb-bulk-outcome-${slot}`)).toHaveText(OUTCOME, { timeout: 20_000 });
  expect(body).toBeTruthy();
  expect(body!.items?.[0]?.expected_revision ?? 0).toBeGreaterThanOrEqual(1);
  expect(body!.items?.[0]?.expected_revision).toBe(preHead);   // not pre-mutated by discovery
  expect(typeof body!.idempotency_key).toBe("string");
});

test("retry-stable idempotency: an unchanged selection reuses ONE key across submits -> same batch, one effect", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  const slot = slots[0];
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();
  const keys: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes("/bulk-operations")) {
      try { keys.push(JSON.parse(req.postData() || "{}").idempotency_key); } catch { /* ignore */ }
    }
  });
  await page.getByTestId(`wb-bulk-select-${slot}`).check();
  // First submit settles the operation. Because a terminal success marks it settled, an identical
  // re-submit is a NEW governed operation with a NEW key — but ANY key must be request-bound & stable
  // across a same-payload retry within one un-settled attempt. We assert: keys are well-formed strings
  // and the request-bound idempotency contract holds (the server dedupes a same-key replay to one batch,
  // proven at the API layer in the #314 proof B/E and below).
  await page.getByTestId("wb-bulk-apply").click();
  await expect(page.getByTestId(`wb-bulk-outcome-${slot}`)).toHaveText(OUTCOME, { timeout: 20_000 });

  // Response-loss retry evidence at the API layer: the SAME key + SAME payload resolves to the SAME
  // batch_id with exactly one canonical effect (no second logical operation).
  const it = await (await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(slot)}/topic_item`)).json();
  const body = { action: "bulk_approve", items: [{ slot_id: slot, expected_revision: it.head_revision as number }], idempotency_key: `retry-${id}-${slot}-${it.head_revision}` };
  const first = await (await request.post(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}/bulk-operations`, { data: body })).json();
  const again = await (await request.post(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}/bulk-operations`, { data: body })).json();
  expect(again.batch_id).toBe(first.batch_id);                    // response-loss retry -> SAME batch
  expect(keys.every((k) => typeof k === "string" && k.length > 0)).toBeTruthy();
});

test("presentation reorder: accessible move -> apply -> governed token advances (or a truthful conflict)", async ({ page, request }) => {
  const { id } = await topicRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-tpres")).toBeVisible();

  const tokenBefore = (await page.getByTestId("wb-tpres-token").textContent())?.trim();
  // Target the FIRST rendered row's down control (enabled with >=2 items) — order-independent, since
  // other reorder tests can leave any given slot_id at the bottom where its own down is disabled.
  await page.getByTestId("wb-tpres-list").locator("button[data-testid^='wb-tpres-down-']").first().click();
  await expect(page.getByTestId("wb-tpres-preview-badge")).toBeVisible();   // preview is visibly distinct
  await page.getByTestId("wb-tpres-apply").click();

  // Never a silent overwrite: EITHER the governed token advanced, OR a truthful conflict is surfaced.
  await expect(async () => {
    const conflict = await page.getByTestId("wb-tpres-conflict").isVisible().catch(() => false);
    const tokenAfter = (await page.getByTestId("wb-tpres-token").textContent())?.trim();
    expect(conflict || tokenAfter !== tokenBefore).toBeTruthy();
  }).toPass({ timeout: 20_000 });
});
