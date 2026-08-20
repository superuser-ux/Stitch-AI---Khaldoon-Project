import { test, expect, type APIRequestContext } from "@playwright/test";
import { WB_URL, VIEWPORTS } from "./surfaces";

// #313 Stage 2B-1 — the production-shaped per-item Topic governance flow. NON-SKIPPING by
// construction: it discovers a run with a generated Topic through the real read path and drives a
// governed structured edit end to end — actual V2 UI -> /gw allowlist -> live API -> canonical
// command -> durable DB revision -> read model -> rendered result. No mocked client state.

/** A run whose Stage 2A read model has at least one generated Topic; returns its first generated slot. */
async function generatedRun(request: APIRequestContext) {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const res = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}/generation`);
    if (!res.ok()) continue;
    const m = await res.json();
    if (!m.stage2a_enabled) continue;
    // #355 — "has a generated topic" is not the same as "can be acted on". A run at TOPIC_APPROVED
    // has generated topics whose items the server refuses to edit, so on a lane holding runs at
    // several stages this could select a run these tests cannot act on and fail for a fixture reason
    // that looks like a product defect. Eligibility comes from the SERVER's action map.
    for (const g of (m.results || []) as { topic: unknown; slot_id: string }[]) {
      if (!g.topic) continue;
      const item = await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(g.slot_id)}/topic_item`);
      if (!item.ok()) continue;
      const model = await item.json();
      if (model?.actions?.edit?.allowed === true) return { id: r.round_id as string, slot: g.slot_id };
    }
  }
  throw new Error(
    "no generated run whose Topic items the SERVER reports as editable — the fixture must provision " +
    "one (a run at TOPIC_APPROVED does not qualify); a skip would hide real defects",
  );
}

test("inspect/history renders + structured edit appends a durable new revision through the canonical command", async ({ page, request }) => {
  const { id, slot } = await generatedRun(request);
  // Read the current durable head so the test is robust to prior runs (revisions are append-only and
  // persist across runs); assert the edit increments it, never a hardcoded revision number.
  const rm = await (await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(slot)}/topic_item`)).json();
  const head0 = rm.head_revision as number;
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);

  // Capture the outgoing edit write to PROVE the B2 tokens are on the wire (Codex P1-4): the request
  // must visibly carry the expected_revision CAS token and an idempotency_key.
  let editBody: Record<string, unknown> | null = null;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes(`/gw/slots/${encodeURIComponent(slot)}/edit`)) {
      try { editBody = JSON.parse(req.postData() || "{}"); } catch { editBody = {}; }
    }
  });

  const panel = page.getByTestId(`wb-topic-item-${slot}`);
  await expect(panel).toBeVisible();
  // Read model rendered from durable server truth (head pointer + append-only history).
  await expect(page.getByTestId(`wb-topic-item-head-${slot}`)).toHaveText(new RegExp(`head rev ${head0}`));
  await expect(page.getByTestId(`wb-topic-item-history-${slot}`).locator(":scope > li")).toHaveCount(head0);
  await expect(page.getByTestId(`wb-topic-item-rev-${slot}-1`)).toBeVisible();
  // The source-language value renders with bidi isolation (never a fabricated or reordered source).
  await expect(page.getByTestId(`wb-topic-item-rev-${slot}-1`).locator("bdi")).toHaveAttribute("dir", "auto");

  // The one governed WRITE — a structured edit — flows through /gw -> canonical edit command with an
  // expected-revision CAS, and the durable new revision comes back through the read model.
  await page.getByTestId(`wb-topic-item-edit-${slot}`).fill("زاوية محرَّرة عبر واجهة V2");
  await page.getByTestId(`wb-topic-item-edit-save-${slot}`).click();

  await expect(page.getByTestId(`wb-topic-item-rev-${slot}-${head0 + 1}`)).toBeVisible();
  await expect(page.getByTestId(`wb-topic-item-head-${slot}`)).toHaveText(new RegExp(`head rev ${head0 + 1}`));
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toContainText("new revision");
  // the new revision derives from the prior head (append-only parent/base lineage), still present.
  await expect(page.getByTestId(`wb-topic-item-rev-${slot}-${head0 + 1}`)).toContainText(`← ${head0}`);
  await expect(page.getByTestId(`wb-topic-item-rev-${slot}-1`)).toBeVisible();
  // The write carried the CAS + idempotency tokens visibly on the wire.
  expect(editBody, "the edit request was captured").not.toBeNull();
  expect(editBody!.expected_revision, "edit carries the expected_revision CAS token").toBe(head0);
  expect(typeof editBody!.idempotency_key, "edit carries an idempotency_key token").toBe("string");
});

test("governed action family: typed-action buttons + identity disclosure + a real drop through the canonical command", async ({ page, request }) => {
  const { id, slot } = await generatedRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible();

  // Identity is disclosed truthfully — slot_id is the stable key, topic_id is per-revision (Blocker 4).
  const identity = page.getByTestId(`wb-topic-item-identity-${slot}`);
  await expect(identity).toHaveAttribute("data-stable-key", "slot_id");
  await expect(identity).toContainText("per-revision");

  // In-review: the whole governed family is OFFERED (server marks each allowed), never a client guess.
  for (const verb of ["approve", "request_change", "rework", "drop"] as const) {
    await expect(page.getByTestId(`wb-topic-item-action-${verb}-${slot}`)).toHaveAttribute("data-allowed", "true");
  }

  // Capture the approve write to prove it carries the exact-revision CAS token (Codex P1-1).
  let approveBody: Record<string, unknown> | null = null;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes(`/gw/slots/${encodeURIComponent(slot)}/approve`)) {
      try { approveBody = JSON.parse(req.postData() || "{}"); } catch { approveBody = {}; }
    }
  });
  await page.getByTestId(`wb-topic-item-action-approve-${slot}`).click();
  // Approve RECORDS a decision for the exact revision; it does NOT transition (human commit floor).
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toContainText("decision recorded");
  expect(typeof approveBody!.expected_revision, "approve carries the exact-revision CAS token").toBe("number");

  // A DROP routes through the governed gate reject decision — truthfully "decision recorded", not a
  // phantom transition — and is non-destructive: the append-only history is still fully present.
  await page.getByTestId(`wb-topic-item-action-drop-${slot}`).click();
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toContainText("decision recorded");
  await expect(page.getByTestId(`wb-topic-item-rev-${slot}-1`)).toBeVisible();
});

test("the per-item panel renders without horizontal overflow at every viewport, LTR + RTL", async ({ page, request }) => {
  const { id, slot } = await generatedRun(request);
  for (const dir of ["ltr", "rtl"] as const) {
    for (const vp of VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
      await page.evaluate((d) => document.documentElement.setAttribute("dir", d), dir);
      await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `no horizontal overflow at ${vp.label}/${dir}`).toBeLessThanOrEqual(1);
    }
  }
});
