import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { WB_URL, VIEWPORTS } from "./surfaces";

// #315 Stage 2B-3 — bilingual / responsive / accessibility contract over the shipped #313/#314 Topic
// semantics. Production-shaped V2 → /gw → live API/read model. Per the Codex ruling: canonical
// mutation/CAS/idempotency/source-BYTE claims run on the LIVE path; controlled UI interception is used
// ONLY for deterministic DISPLAY-state rendering (bilingual 4-state, operational states). Non-skipping.

async function topicRun(request: APIRequestContext) {
  // #355 — the status regex alone is NOT an eligibility test. `/TOPIC|CHANGE/i` also matches
  // TOPIC_APPROVED, whose items the server correctly refuses to edit ("approved"), so on a lane
  // holding runs at several stages this selector could return a run these tests cannot act on and
  // fail for a fixture reason that looks like a product defect. Eligibility is therefore taken from
  // the SERVER's own action map — the same rule #313/#346 established: never infer which actions are
  // permitted, ask.
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  for (const r of rows as { round_id: string }[]) {
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(r.round_id)}`)).json();
    const candidates = (d.slots || []).filter((s: { status?: string }) => /TOPIC|CHANGE/i.test(s.status || "")) as { slot_id: string }[];
    const actionable: string[] = [];
    for (const s of candidates) {
      const item = await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(s.slot_id)}/topic_item`);
      if (!item.ok()) continue;
      const model = await item.json();
      if (model?.actions?.edit?.allowed === true) actionable.push(s.slot_id);
    }
    if (actionable.length >= 1) return { id: r.round_id as string, slots: actionable };
  }
  throw new Error(
    "no run whose Topic items the SERVER reports as editable — the fixture must provision one " +
    "(a run at TOPIC_APPROVED does not qualify); a skip would hide defects",
  );
}

/** A controlled topic_item read model (for DISPLAY-state determinism only — never a mutation claim). */
function fakeItem(slot: string, rev: Partial<{ change_summary_ar: string | null; change_summary_en: string | null; body: string | null }>) {
  return {
    slot_id: slot, artifact: "topic", status: "TOPIC_PROPOSED", head_revision: 1, approved_revision: null,
    identity: { stable_key: "slot_id", slot_id: slot, topic_id_scope: "per_revision" },
    revisions: [{ revision: 1, topic_id: "t0", body: rev.body ?? "زاوية عربية", change_summary_ar: rev.change_summary_ar ?? null, change_summary_en: rev.change_summary_en ?? null, approved: false }],
    actions: { edit: { allowed: true } },
  };
}

async function routeItem(page: Page, slot: string, rev: Parameters<typeof fakeItem>[1]) {
  await page.route(`**/gw/slots/${slot}/topic_item`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fakeItem(slot, rev)) }));
}

/** The SOURCE-CONTENT bytes of the LIVE append-only history (body + change summaries + per-revision
 *  topic_id), normalized + revision-sorted so two reads compare byte-for-byte with a single
 *  JSON.stringify equality. Governance metadata (approved/status) is deliberately EXCLUDED: a governed
 *  decision (e.g. bulk approve) may flip it, but that is not a source-byte change — the claim under
 *  test is that the canonical Topic CONTENT is preserved. Live path only (never a routed fake) because
 *  this underpins canonical-source claims. */
async function sourceBytes(request: APIRequestContext, slot: string) {
  const rm = await (await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(slot)}/topic_item`)).json();
  return (rm.revisions as Record<string, unknown>[])
    .map((r) => ({
      revision: r.revision as number,
      body: (r.body ?? null) as string | null,
      topic_id: (r.topic_id ?? null) as string | null,
      change_summary_ar: (r.change_summary_ar ?? null) as string | null,
      change_summary_en: (r.change_summary_en ?? null) as string | null,
    }))
    .sort((a, b) => a.revision - b.revision);
}

test("bilingual change-summary renders all four deterministic states with truthful per-node lang/dir + disclosure", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  const slot = slots[0];
  const tid = `wb-topic-item-change-summary-${slot}-1`;
  const cases: [Parameters<typeof fakeItem>[1], string, boolean, boolean][] = [
    [{ change_summary_ar: "ملخص عربي", change_summary_en: "English summary" }, "bilingual", true, true],
    [{ change_summary_ar: "ملخص عربي فقط", change_summary_en: null }, "arabic-only", true, false],
    [{ change_summary_ar: null, change_summary_en: "English only" }, "english-only", false, true],
    [{ change_summary_ar: null, change_summary_en: null }, "missing", false, false],
  ];
  for (const [rev, state, hasAr, hasEn] of cases) {
    await routeItem(page, slot, rev);
    await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
    // ALL four states — including `missing` — render truthfully in the ACTUAL surface. `missing` is a
    // disclosed state (data-bilingual-state="missing" + the "not provided in either language"
    // disclosure), never absence-of-UI. Redefining missing as "not shown" would hide the real state.
    const el = page.getByTestId(tid);
    await expect(el).toHaveAttribute("data-bilingual-state", state);
    await expect(page.getByTestId(`${tid}-ar`)).toHaveCount(hasAr ? 1 : 0);
    await expect(page.getByTestId(`${tid}-en`)).toHaveCount(hasEn ? 1 : 0);
    if (hasAr) await expect(page.getByTestId(`${tid}-ar`)).toHaveAttribute("lang", "ar");
    if (hasEn) await expect(page.getByTestId(`${tid}-en`)).toHaveAttribute("lang", "en");
    // arabic-only, english-only AND missing each disclose the absent side(s) — never fabricated.
    if (!hasAr || !hasEn) await expect(page.getByTestId(`${tid}-fallback`)).toBeVisible();
  }
});

// #315 ruling 2 (Codex reconciliation — Option B, comment 5011184074). The byte guarantee is split
// into the two claims that are actually TRUE of this system, and NO false raw-whitespace-persistence
// claim is made:
//   (a) V2 transmits the deliberate edit value byte-for-byte (raw wire equality); `trim()` is only the
//       non-empty submit predicate, never a transform of the transmitted bytes.
//   (b) The persisted value is the SERVER-canonicalized form. `edit_revision`'s strip() is pre-existing
//       shared/V1 backend behavior; #315 does NOT alter it. We assert + DISCLOSE the canonicalized
//       value rather than falsely claiming whitespace preservation. No client/display normalization is
//       applied on top of the server's own canonicalization.
test("edit transmits RAW bytes on the wire; the persisted value is the server-canonicalized form (disclosed, no client normalization)", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  const slot = slots[0];
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slot}`)).toBeVisible();

  // snapshot the append-only history BEFORE the edit — every prior revision's bytes must survive intact.
  const before = await sourceBytes(request, slot);

  const raw = `  زاوية ذات مسافات ${Date.now()}  `;                 // leading/trailing whitespace ON PURPOSE
  let sent: { value?: string } | null = null;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().includes(`/gw/slots/${slot}/edit`)) {
      try { sent = JSON.parse(req.postData() || "{}"); } catch { sent = {}; }
    }
  });
  await page.getByTestId(`wb-topic-item-edit-${slot}`).fill(raw);
  await page.getByTestId(`wb-topic-item-edit-save-${slot}`).click();
  await expect(page.getByTestId(`wb-topic-item-write-msg-${slot}`)).toBeVisible({ timeout: 20_000 });

  // (a) RAW wire equality — the transmitted bytes are EXACTLY what the reviewer entered.
  expect(sent, "edit request captured").toBeTruthy();
  expect(sent!.value, "RAW bytes on the wire — V2 never client-normalizes the source").toBe(raw);

  // (b) Persisted value == the SERVER-canonicalized (strip) form. Disclosed existing backend behavior,
  //     NOT a #315 defect and NOT a raw-whitespace-persistence claim.
  const after = await sourceBytes(request, slot);
  const head = after.reduce((a, b) => (b.revision > a.revision ? b : a));
  expect(head.body, "persisted value == server-canonicalized (strip) of the raw edit — disclosed backend behavior").toBe(raw.trim());

  // append-only immutability: every revision that existed before the edit is byte-identical after it.
  for (const prev of before) {
    const still = after.find((r) => r.revision === prev.revision) ?? null;
    expect(JSON.stringify(still), `prior revision ${prev.revision} bytes are immutable (append-only)`).toBe(JSON.stringify(prev));
  }
});

// #346 — EXPLICIT, NON-MUTATING fixture eligibility.
//
// #345's isolated gate exposed two failures here (`wb-topic-item-history-RE2E-1`, `wb-bulk-result`).
// Neither was flaky. The helpers selected a run that merely *contained* Topic items, which is a
// different question from whether the run can render the history surface or accept a bulk action.
// Against contaminated state the selection happened to land on a capable run; on a deterministic
// lane it did not, and the tests failed on a surface that could never have existed for that run.
//
// TWO SEPARATE CONTRACTS, because they are genuinely independent predicates:
//
//   HISTORY  `wb-topic-item-history-{slot}` is rendered by TopicItemPanel, which generation-seam
//            mounts per STAGE 2A GENERATION RESULT. A slot at TOPIC_PROPOSED is NOT sufficient: a
//            seed-provisioned run with no generation job renders no panel at all, so the testid can
//            never appear. Eligibility is therefore read from `/rounds/{id}/generation`.
//
//   BULK     `wb-bulk-result` renders only once a bulk apply returns. Eligibility is the run having
//            an open topic_review posture and enough in-review slots whose SERVER-OWNED action map
//            permits the action.
//
// DISCOVERY NEVER MUTATES (#346 ruling). The previous helper proved bulk eligibility by performing a
// real `bulk_approve` on a "sacrificial" slot. That made discovery a state change: every invocation
// consumed one in-review slot, so two tests sharing a lane could drop the run below the >=2 threshold
// and make outcomes order-dependent — the exact class of defect this directive removes. Eligibility
// is now read ONLY from the enumerated read boundary (`/rounds`, `/rounds/{id}`,
// `/rounds/{id}/generation`, `/slots/{id}/topic_item`). The TEST ACTION ITSELF is the sole proof of
// bulk authority; if the server refuses it, the test FAILS rather than being pre-screened away.

type Candidate = {
  id: string;
  inReview: string[];
  generatedSlots: string[];
  actionable: string[];
  openTopicGate: boolean;
  missing: string[];
};

// The gate read model is not on V2's read allowlist (`/gw/gates` is refused by design — V2 reads a
// deliberately enumerated surface). The suite already reads the API directly for exactly this kind of
// governed-state check (see schedule-views.spec.ts), so the gate posture is read the same way. Still a
// pure GET; nothing is decided, resolved, or mutated.
const API = process.env.API_BASE || "http://localhost:8009";

/** Rounds with an OPEN topic_review gate, read non-mutatingly.
 *
 *  This is a SEPARATE signal from the per-item action map, and the distinction is load-bearing: a slot
 *  can report `approve: {allowed: true}` while `bulk-operations` refuses the round outright with
 *  "no open topic_review gate". The per-item map answers "may this item be approved?"; the bulk
 *  endpoint additionally requires the round-level review gate to be open. Treating the action map as
 *  sufficient selects a run the bulk surface will reject — which is precisely the failure this
 *  directive is correcting, one layer deeper than it first appeared. */
async function roundsWithOpenTopicGate(request: APIRequestContext): Promise<Set<string>> {
  const res = await request.get(`${API}/gates`);
  if (!res.ok()) return new Set();
  const raw = await res.json();
  const gates = (Array.isArray(raw) ? raw : raw.gates || []) as
    { stage?: string; status?: string; round_id?: string }[];
  return new Set(
    gates.filter((g) => g.stage === "topic_review" && g.status === "open" && g.round_id)
      .map((g) => g.round_id as string),
  );
}

const BULK_MIN_SLOTS = 2;          // the bulk surface asserts a selection; one slot cannot prove it
const BULK_ACTION = "approve";     // the action the bulk tests drive

/** Enumerate the COMPLETE candidate set once, evaluating both contracts per run from the supported
 *  read paths only. No DOM, no identifier parsing, no ordering/timestamp inference, no mutation. */
async function enumerateCandidates(request: APIRequestContext): Promise<Candidate[]> {
  const rows = (await (await request.get(`${WB_URL}/gw/rounds`)).json()) as { round_id: string }[];
  const openGates = await roundsWithOpenTopicGate(request);
  const out: Candidate[] = [];
  for (const r of rows) {
    const id = r.round_id;
    const d = await (await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}`)).json();
    const inReview = ((d.slots || []) as { slot_id: string; status?: string }[])
      .filter((s) => /TOPIC|CHANGE/i.test(s.status || ""))
      .map((s) => s.slot_id)
      .sort();                                   // stable, independent of database return order

    // HISTORY: which slots the Stage 2A read model actually reports a generated Topic for. This is
    // what decides whether TopicItemPanel mounts, and therefore whether the history list exists.
    let generatedSlots: string[] = [];
    const gRes = await request.get(`${WB_URL}/gw/rounds/${encodeURIComponent(id)}/generation`);
    if (gRes.ok()) {
      const g = await gRes.json();
      if (g.stage2a_enabled && (g.jobs?.length ?? 0) > 0) {
        generatedSlots = ((g.results || []) as { slot_id: string; topic?: unknown }[])
          .filter((x) => x.topic)
          .map((x) => x.slot_id)
          .sort();
      }
    }

    // BULK: the server's own action map per in-review slot. Read verbatim — never inferred, and
    // never established by performing the action.
    const actionable: string[] = [];
    for (const s of inReview) {
      const iRes = await request.get(`${WB_URL}/gw/slots/${encodeURIComponent(s)}/topic_item`);
      if (!iRes.ok()) continue;
      const it = await iRes.json();
      const a = (it.actions || {})[BULK_ACTION];
      if (a && a.allowed === true) actionable.push(s);
    }

    const openTopicGate = openGates.has(id);

    const missing: string[] = [];
    if (generatedSlots.length < 1) missing.push("history: no Stage 2A generated Topic (enabled+job+result)");
    if (!openTopicGate) missing.push("bulk: no OPEN topic_review gate for the round");
    if (inReview.length < BULK_MIN_SLOTS) missing.push(`bulk: only ${inReview.length} in-review slot(s), need >=${BULK_MIN_SLOTS}`);
    if (actionable.length < BULK_MIN_SLOTS) missing.push(`bulk: only ${actionable.length} slot(s) with server-permitted '${BULK_ACTION}'`);
    out.push({ id, inReview, generatedSlots, actionable: actionable.sort(), openTopicGate, missing });
  }
  return out;
}

/** Stable tie-breaker: lexicographic round_id among qualifying candidates. Deliberately NOT "first
 *  returned" — database/API ordering is not a contract, and depending on it is what made these
 *  tests pass or fail by accident. */
function pick(qualifying: Candidate[]): Candidate {
  return [...qualifying].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))[0];
}

/** Fail BEFORE navigation or any interaction, naming every candidate's missing predicate — so a
 *  provisioning gap reads as a provisioning gap, not as a mysterious missing element mid-test. */
function noCandidate(kind: string, all: Candidate[]): never {
  const detail = all.length
    ? all.map((c) => `  ${c.id}: ${c.missing.length ? c.missing.join("; ") : "(qualifies)"}`).join("\n")
    : "  (no runs returned by /gw/rounds)";
  throw new Error(
    `no ${kind}-eligible run in this lane; a skip would hide the defect. Candidates and missing predicates:\n${detail}\n` +
    "The lane must provision a run through the governed Stage 2A chain (see docs/v2-transition/acceptance-lane-342.md " +
    "and #345): POST /rounds -> open schedule_review gate -> decide(approve) -> resolve. Seeded Topic rows alone " +
    "do NOT create a generation job and therefore never render the history surface.",
  );
}

// The two contracts, named and stated once. Both are pure predicates over the enumerated read-model
// evidence — they are the single definition each selector below composes, so "history-eligible" and
// "bulk-eligible" cannot drift apart between call sites.

/** HISTORY: the Stage 2A read model reports a generated Topic, so TopicItemPanel mounts. */
const hasHistoryEvidence = (c: Candidate) => c.generatedSlots.length >= 1;

/** BULK: the server's own action map permits the action on enough in-review slots. */
const hasBulkEvidence = (c: Candidate) => c.openTopicGate && c.actionable.length >= BULK_MIN_SLOTS;

/** A run the SERVER says is bulk-actionable on enough in-review slots. Non-mutating: the action map
 *  is read, never exercised. The test's own bulk apply remains the only authority proof. */
async function bulkEligibleRun(request: APIRequestContext): Promise<{ id: string; slots: string[] }> {
  const all = await enumerateCandidates(request);
  const ok = all.filter(hasBulkEvidence);
  if (!ok.length) noCandidate("bulk", all);
  const c = pick(ok);
  return { id: c.id, slots: c.actionable };
}

/** Test A drives BOTH surfaces in one run, so it needs a run satisfying both contracts. The returned
 *  slots are generated AND server-permitted, so the history assertion and the bulk selection address
 *  the same canonical items. */
async function historyAndBulkEligibleRun(request: APIRequestContext): Promise<{ id: string; slots: string[] }> {
  const all = await enumerateCandidates(request);
  const ok = all.filter((c) => hasHistoryEvidence(c) && hasBulkEvidence(c));
  if (!ok.length) noCandidate("history+bulk", all);
  const c = pick(ok);
  const both = c.generatedSlots.filter((s) => c.actionable.includes(s));
  if (both.length < BULK_MIN_SLOTS) noCandidate("history+bulk", all);
  return { id: c.id, slots: both };
}

// #315 ruling 2 (Option B), review findings 4 + re-review 1 — the non-content half must EXECUTE the
// paths it claims to prove, and NON-VACUOUSLY: a SUCCESSFUL governed bulk disposition (outcome
// `succeeded`) AND a SUCCESSFUL presentation reorder (the governed token ADVANCES) must both occur, and
// the affected slots' canonical Topic SOURCE bytes must be byte-for-byte unchanged before/after. (An
// approve/reorder never rewrites `body`; reorder is presentation-only.) Conflict-path evidence lives
// separately (operational-states CONFLICT) — it is NOT a substitute for this success proof. No routed
// fakes — the byte claim is genuinely against the live API/DB.
test("LIVE bulk (succeeded) + LIVE reorder (token advances) preserve canonical Topic source bytes byte-for-byte", async ({ page, request }) => {
  // #346 — this test asserts the history surface AND drives a live bulk, so it needs a run proven
  // eligible for BOTH. Selecting on Topic-items alone is what made it fail on a deterministic lane.
  const { id, slots } = await historyAndBulkEligibleRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();
  await expect(page.getByTestId("wb-tpres")).toBeVisible();

  // baseline SOURCE-content bytes for every in-review slot.
  const baseline: Record<string, string> = {};
  for (const s of slots) baseline[s] = JSON.stringify(await sourceBytes(request, s));

  // --- display transitions (must not mutate) ---
  await expect(page.getByTestId(`wb-topic-item-history-${slots[0]}`)).toBeVisible();  // inspect/history
  await page.getByTestId("wb-dir-toggle").click();                                    // language/direction (display)
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByTestId("wb-dir-toggle").click();

  // --- LIVE bulk disposition — REQUIRE `succeeded` (non-vacuous) ---
  const target = slots[0];
  await page.getByTestId(`wb-bulk-select-${target}`).check();
  await expect(page.getByTestId("wb-bulk-selected")).toHaveText(/1 selected/);
  await page.getByTestId("wb-bulk-apply").click();
  await expect(page.getByTestId(`wb-bulk-outcome-${target}`)).toContainText("succeeded", { timeout: 20_000 });

  // --- LIVE presentation reorder — REQUIRE the governed token to ADVANCE (success, not conflict) ---
  const tokenBefore = (await page.getByTestId("wb-tpres-token").textContent())?.trim();
  await page.getByTestId("wb-tpres-list").locator("button[data-testid^='wb-tpres-down-']").first().click();
  await expect(page.getByTestId("wb-tpres-preview-badge")).toBeVisible();
  await page.getByTestId("wb-tpres-apply").click();
  await expect(page.getByTestId("wb-tpres-status")).toBeVisible({ timeout: 20_000 });   // SUCCESS announce, not conflict
  await expect(page.getByTestId("wb-tpres-conflict")).toHaveCount(0);
  await expect
    .poll(async () => (await page.getByTestId("wb-tpres-token").textContent())?.trim(), { timeout: 20_000 })
    .not.toBe(tokenBefore);                                                              // governed version ADVANCED

  // canonical SOURCE bytes of every slot are byte-for-byte unchanged after the SUCCESSFUL commands + display.
  for (const s of slots) {
    expect(JSON.stringify(await sourceBytes(request, s)),
      `slot ${s} canonical Topic source bytes unchanged by successful bulk/reorder + display`).toBe(baseline[s]);
  }
});

test("language semantics: RTL toggle keeps chrome lang=en, flips dir, Arabic content carries lang=ar", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.getByTestId("wb-dir-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html"), "chrome stays English under RTL (no AT mislabel)").toHaveAttribute("lang", "en");
  await expect(page.getByTestId(`wb-topic-item-rev-${slots[0]}-1`).locator("bdi[lang='ar']").first()).toBeVisible();
});

// #315 review finding 5 / re-review 3 — the DirToggle must ADOPT the authoritative document direction
// on mount, not drift back to LTR. Set RTL on the run route, then CLIENT-navigate (no reload) to the
// home route so <html dir> persists; the home DirToggle must remount already showing aria-pressed=true
// with a STABLE accessible name. A hardcoded-LTR toggle would fail this.
test("DirToggle adopts the authoritative document direction across a route remount (no drift), stable a11y name", async ({ page, request }) => {
  const { id } = await topicRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  const toggle = page.getByTestId("wb-dir-toggle");
  await expect(toggle).toHaveAttribute("aria-label", "Right-to-left text direction");   // stable name
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await toggle.click();                                                                  // RTL on the run route
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");

  // CLIENT-side navigation via the breadcrumb <Link> — no document reload, so <html dir> survives.
  await page.getByTestId("back-to-schedule").click();
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");                      // direction persisted
  const homeToggle = page.getByTestId("wb-dir-toggle");
  await expect(homeToggle).toHaveAttribute("aria-pressed", "true");                      // ADOPTED on remount — no drift
  await expect(homeToggle).toHaveAttribute("aria-label", "Right-to-left text direction"); // still stable
});

test("keyboard-only edit: no trap, focus restored to the announced status region after completion", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  const slot = slots[0];
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  const box = page.getByTestId(`wb-topic-item-edit-${slot}`);
  await box.focus();
  await box.fill(`زاوية بلوحة المفاتيح ${Date.now()}`);
  await page.getByTestId(`wb-topic-item-edit-save-${slot}`).focus();   // reachable by keyboard
  await page.keyboard.press("Enter");
  const status = page.getByTestId(`wb-topic-item-write-msg-${slot}`);
  await expect(status).toBeVisible({ timeout: 20_000 });
  await expect(status).toBeFocused();                                  // focus restored, not stranded
  await expect(status).toHaveAttribute("role", "status");
});

// #315 review finding 2 — keyboard-only bulk SUCCESS restores focus to the announced status region.
test("keyboard-only bulk disposition: focus restored to the announced status region after completion", async ({ page, request }) => {
  // #346 — `wb-bulk-result` only renders once a bulk apply RETURNS, so this needs a run the server
  // itself reports as bulk-actionable. Discovery reads the action map; it never performs the action —
  // the apply below remains the sole proof of bulk authority, and a refusal fails this test.
  const { id, slots } = await bulkEligibleRun(request);
  const slot = slots[0];
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-bulk")).toBeVisible();
  await page.getByTestId(`wb-bulk-select-${slot}`).focus();
  await page.keyboard.press("Space");                                 // select by keyboard
  await expect(page.getByTestId("wb-bulk-selected")).toHaveText(/1 selected/);
  await page.getByTestId("wb-bulk-apply").focus();                    // reachable by keyboard
  await page.keyboard.press("Enter");
  const status = page.getByTestId("wb-bulk-result");
  await expect(status).toBeVisible({ timeout: 20_000 });
  await expect(status).toBeFocused();                                 // focus restored, not stranded
  await expect(status).toHaveAttribute("role", "status");
});

// #315 review finding 2 — keyboard-only reorder restores focus to the settled announced region
// (success status OR a truthful conflict — never a silent overwrite, never a stranded focus).
test("keyboard-only presentation reorder: focus restored to the settled announced region after apply", async ({ page, request }) => {
  const { id, slots } = await topicRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId("wb-tpres")).toBeVisible();
  // FIRST rendered row's down control (enabled with >=2 items) — order-independent (see byte test).
  await page.getByTestId("wb-tpres-list").locator("button[data-testid^='wb-tpres-down-']").first().focus();
  await page.keyboard.press("Enter");                                 // move -> preview
  await expect(page.getByTestId("wb-tpres-preview-badge")).toBeVisible();
  await page.getByTestId("wb-tpres-apply").focus();
  await page.keyboard.press("Enter");                                 // commit
  await expect(async () => {
    const s = await page.getByTestId("wb-tpres-status").isVisible().catch(() => false);
    const c = await page.getByTestId("wb-tpres-conflict").isVisible().catch(() => false);
    expect(s || c).toBeTruthy();
  }).toPass({ timeout: 20_000 });
  const settledId = (await page.getByTestId("wb-tpres-status").isVisible().catch(() => false))
    ? "wb-tpres-status" : "wb-tpres-conflict";
  await expect(page.getByTestId(settledId)).toBeFocused();            // focus restored to the settled region
});

test("reduced motion: the review flow is fully usable with prefers-reduced-motion", async ({ browser, request }) => {
  const ctx = await browser.newContext({ reducedMotion: "reduce" });
  const page = await ctx.newPage();
  const { id, slots } = await topicRun(request);
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
  await expect(page.getByTestId(`wb-topic-item-${slots[0]}`)).toBeVisible();
  await ctx.close();
});

for (const vp of VIEWPORTS) {
  for (const dir of ["ltr", "rtl"] as const) {
    test(`no horizontal overflow — per-item + bulk + reorder @ ${vp.label} ${dir}`, async ({ page, request }) => {
      const { id } = await topicRun(request);
      await page.setViewportSize({ width: vp.width, height: 900 });
      await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review`);
      if (dir === "rtl") await page.getByTestId("wb-dir-toggle").click();
      for (const tid of ["run-topic-disposition", "wb-bulk", "wb-tpres"]) {
        const el = page.getByTestId(tid).first();
        if (await el.count()) {
          const overflow = await el.evaluate((n) => n.scrollWidth - n.clientWidth);
          expect(overflow, `${tid} overflows at ${vp.width}px ${dir}`).toBeLessThanOrEqual(1);
        }
      }
    });
  }
}
