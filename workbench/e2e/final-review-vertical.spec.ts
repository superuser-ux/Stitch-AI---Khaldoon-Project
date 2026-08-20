import { test, expect, type Page, type Route } from "@playwright/test";
import { WB_URL } from "./surfaces";

// R1 Stage 4 — bounded browser evidence for the V2 Final Review VERTICAL.
//
// WHAT THIS SUITE IS, AND WHAT IT DELIBERATELY IS NOT.
//
// It is TWO lanes with different evidential weight, kept visibly apart:
//
//   LANE A — the REAL /gw seam, no stubs. Proves the boundary admits exactly the two canonical
//            authority operations and still refuses everything adjacent. Needs no fixture and no
//            backend for admission; the runtime posture (TANAGHOM_DEV_MODE) is reported, never hidden.
//
//   LANE B — deterministic UI regression over STUBBED SERVER READS. Every stub is a stand-in for
//            SERVER-AUTHORED TRUTH the surface renders; none of them fakes authority. That distinction
//            is the whole basis on which stubbing is legitimate here: the assertions are about what
//            this surface DOES WITH the server's answer (which request it sends, which control it
//            withholds, what it refuses to conclude) — never about whether the real gate authority
//            would accept anything. A stubbed 200 from `decide` proves the client sent a correct
//            request and classified the reply; it proves NOTHING about the canonical command, and this
//            suite never claims otherwise.
//
// Whether the canonical authority actually decides and advances is proven ONLY by the exact-head
// live/Orca browser lane against the real API. These two lanes are complementary and neither
// substitutes for the other — a green run here is not vertical completion on its own.

const ROUND = "RFIN";
const GATE = "11111111-1111-1111-1111-111111111111";
const SLOT_A = "RFIN-1";
const SLOT_B = "RFIN-2";
const SNAP = "22222222-2222-2222-2222-222222222222";
const WF = "33333333-3333-3333-3333-333333333333";

// --------------------------------------------------------------------------- //
// LANE A — the real /gw boundary
// --------------------------------------------------------------------------- //

test.describe("R1 Stage 4 — the /gw boundary admits the canonical authority, and nothing adjacent", () => {
  test("the seam ADMITS the canonical gate DECISION path", async ({ request }) => {
    const res = await request.post(`${WB_URL}/gw/gates/${GATE}/decide`, {
      data: { decision: "approve", slot_ids: [SLOT_A], revision: 1 },
    });
    // Runtime posture, reported rather than masked: outside an explicit dev/test runtime /gw refuses
    // to sign BEFORE the allowlist is consulted, so this case cannot prove admission there.
    test.skip(res.status() === 501,
      "write runtime absent (TANAGHOM_DEV_MODE unset): /gw refuses to sign before the allowlist is consulted");
    expect(res.status(), "decide must be inside the write boundary").not.toBe(403);
    expect(await res.text()).not.toContain("not in the workbench write boundary");
  });

  test("the seam ADMITS the canonical LIFECYCLE TRANSITION path", async ({ request }) => {
    const res = await request.post(`${WB_URL}/gw/gates/${GATE}/resolve`, { data: { slot_ids: [SLOT_A] } });
    test.skip(res.status() === 501,
      "write runtime absent (TANAGHOM_DEV_MODE unset): /gw refuses to sign before the allowlist is consulted");
    expect(res.status(), "resolve must be inside the write boundary").not.toBe(403);
    expect(await res.text()).not.toContain("not in the workbench write boundary");
  });

  test("the boundary was widened by EXACT entries, not by a prefix under /gates", async ({ request }) => {
    // These must stay refused. If a future edit turns the entry into a prefix match, this fails.
    for (const path of [`gates/${GATE}/open`, `gates/${GATE}/decide/extra`, `gates`]) {
      const res = await request.post(`${WB_URL}/gw/${path}`, { data: {} });
      expect([403, 501], `POST /gw/${path} must be refused by the seam`).toContain(res.status());
    }
  });

  test("the READ boundary admits the gate detail and the final-review stage state ONLY", async ({ request }) => {
    // Admission is proven by the ABSENCE of the seam's own boundary refusal — the upstream answer
    // (404/503/200) depends on the environment and is deliberately not asserted.
    for (const path of [`gates/${GATE}`, `rounds/${ROUND}/stages/final_review/state`]) {
      const res = await request.get(`${WB_URL}/gw/${path}`);
      expect(res.status(), `GET /gw/${path} must not be refused at the boundary`).not.toBe(403);
    }
    // Deliberately NOT opened: adding the gate to SERVED_GATES would have exposed both of these.
    for (const path of [`rounds/${ROUND}/stages/final_review/advanced`,
      `rounds/${ROUND}/stages/final_review/action`]) {
      const res = await request.get(`${WB_URL}/gw/${path}`);
      expect(res.status(), `GET /gw/${path} must stay outside the read boundary`).toBe(403);
    }
  });
});

// --------------------------------------------------------------------------- //
// LANE B — deterministic UI regression over stubbed SERVER READS
// --------------------------------------------------------------------------- //

type Outcome = "pending" | "approved" | "rejected" | "changes_requested";

/** The governed workflow artifact. `finalReview` controls whether the generation declares/enables the
 *  stage at all — which is the ONLY thing that decides Final Review reachability. */
function workflowVersion(finalReview: "enabled" | "disabled" | "absent") {
  const stages: Record<string, unknown>[] = [
    {
      stage_key: "script_review", stage_label: "Scripts", stage_group: "Review", ordinal: 3,
      enabled: true, gate_stage: "script_review", stage_kind: "transition",
      generator_kind: "ai", writer_mode: "scripts", generates_from: "topic", approve_to: "APPROVED_ASSIGNED",
    },
  ];
  if (finalReview !== "absent") {
    stages.push({
      stage_key: "final_review", stage_label: "Publish approval", stage_group: "Sign-off", ordinal: 4,
      enabled: finalReview === "enabled", gate_stage: "final_review", stage_kind: "signoff",
      generator_kind: null, writer_mode: null, generates_from: null, approve_to: "READY_FOR_PRODUCTION",
    });
  }
  return { version_id: "v-1", version_no: 7, status: "active", stages };
}

type ServerState = {
  /** Bumped by the harness to model the server having moved. Never bumped by the UI. */
  lifecycle: string;
  gateId: string | null;
  outcomes: Record<string, Outcome>;
  advanced: number;
};

/** Every POST the page issued, in order. The basis for "sign-off advances nothing". */
type Sent = { url: string; body: unknown };

/**
 * Install the stubbed server. Returns the mutable state (so a case can model a server-side change)
 * and the recorded POST log.
 *
 * Reads are stubbed. Writes are stubbed ONLY to return a canonical body — the point of a write case
 * here is the REQUEST that was sent and the classification of the reply, never a claim that the real
 * command would have accepted it.
 */
async function installServer(
  page: Page,
  opts: {
    finalReview?: "enabled" | "disabled" | "absent";
    state?: Partial<ServerState>;
    /** Optional override so a case can model a canonical refusal. */
    onDecide?: (route: Route) => Promise<void> | void;
    onResolve?: (route: Route) => Promise<void> | void;
    preflightAvailable?: boolean;
    tuple?: Record<string, unknown> | null;
  } = {},
): Promise<{ state: ServerState; sent: Sent[] }> {
  const state: ServerState = {
    lifecycle: "reviewing",
    gateId: GATE,
    outcomes: { [SLOT_A]: "pending", [SLOT_B]: "pending" },
    advanced: 0,
    ...opts.state,
  };
  const sent: Sent[] = [];
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/gw/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname.replace(/^\/gw\//, "");
    const method = route.request().method();

    if (method === "POST") {
      let body: unknown = null;
      try { body = route.request().postDataJSON(); } catch { body = route.request().postData(); }
      sent.push({ url: p, body });
      if (p === `gates/${GATE}/decide`) {
        if (opts.onDecide) return opts.onDecide(route);
        // A real decide CHANGES SERVER STATE, so the stub does too. Modelling it here rather than
        // mutating `state` from the test body removes a genuine race: the refetch the decision
        // triggers can otherwise read the gate before the test's assignment runs, and the surface
        // then correctly renders a stale-but-genuine server answer that never updates again.
        const b = (body ?? {}) as { decision?: string; slot_ids?: string[] };
        const next: Outcome = b.decision === "reject" ? "rejected"
          : b.decision === "request_change" ? "changes_requested" : "approved";
        for (const sid of b.slot_ids ?? []) {
          if (sid in state.outcomes) state.outcomes[sid] = next;
        }
        return json(route, { touched: [...(b.slot_ids ?? [SLOT_A])] });
      }
      if (p === `gates/${GATE}/resolve`) {
        if (opts.onResolve) return opts.onResolve(route);
        return json(route, { outcomes: { [SLOT_A]: "approved" } });
      }
      if (p.endsWith("/sign-off")) {
        return json(route, {
          signoff_id: "44444444-4444-4444-4444-444444444444", operation: "sign_off",
          status: "recorded", gate_id: GATE, slot_id: SLOT_A, snapshot_id: SNAP,
          topic_revision: 2, script_revision: 3, workflow_version_id: WF,
          recorded_at: "2026-08-10T12:00:00Z",
        });
      }
      return json(route, { detail: "unstubbed write" }, 500);
    }

    if (p === "workflow-stages/active-enabled" || p === "workflow-stages/active") {
      return json(route, workflowVersion(opts.finalReview ?? "enabled"));
    }
    if (p === `rounds/${ROUND}`) {
      return json(route, { round_id: ROUND, slots: [{ slot_id: SLOT_A }, { slot_id: SLOT_B }] });
    }
    if (p === `rounds/${ROUND}/stages/final_review/state`) {
      return json(route, {
        round_id: ROUND, stage: "final_review", gate_id: state.gateId, state: state.lifecycle,
        in_review: 2, approved: Object.values(state.outcomes).filter((o) => o === "approved").length,
        sent_back: 0, rejected: 0,
        pending: Object.values(state.outcomes).filter((o) => o === "pending").length,
        advanced: state.advanced, recommendation: "server advisory text", warnings: [],
      });
    }
    if (p === `gates/${GATE}`) {
      return json(route, {
        gate_id: GATE, stage: "final_review", status: "open", quorum: 1,
        // Derived from state, NOT a fixed list: an advanced slot stops being a target of this gate,
        // and the stub has to be able to model that or it cannot represent a real transition.
        targets: Object.keys(state.outcomes).map((s) => ({ slot_id: s, current_outcome: state.outcomes[s] })),
      });
    }
    // The COMPLETE canonical shapes. A partial stub is not a smaller truth — the panels are bound to
    // the server's whole payload, so a partial body would exercise a response the server never sends
    // and prove nothing about the real surface.
    if (p.endsWith("/approval-preflight")) {
      const slot = p.split("/")[3];
      const tuple = opts.tuple === undefined
        ? { gate_id: GATE, slot_id: slot, snapshot_id: SNAP, topic_revision: 2, script_revision: 3,
            workflow_version_id: WF }
        : opts.tuple;
      // `available` MODELS THE REAL SERVER PRECONDITION rather than being permanently true.
      // `engine.sign_off` revalidates present authority and the #447/#448 preflight reports
      // `signoff_blocked` — "the present decision outcome is 'pending', which is not an actionable
      // approved state" — until an authoritative APPROVED decision exists. A stub that always said
      // "attemptable" would have modelled a server that does not exist, and is exactly what let an
      // evidence-before-authority ordering look correct here.
      const available = opts.preflightAvailable ?? (state.outcomes[slot] === "approved");
      return json(route, {
        gate_id: GATE, slot_id: slot, available, status: "recorded",
        reason_code: available ? "coherent" : "signoff_blocked",
        detail: "stubbed server-authored preflight",
        target_identity: { gate_id: GATE, slot_id: slot, gate_stage: "final_review",
          gate_status: "open", admitted: true },
        package: null,
        target_package_tuple: tuple,
        evidence: {
          workflow: {
            pinned: { version_id: WF, source: "final_review_target_package" },
            active: { version_id: WF, version_no: 7, status: "active" },
            divergent: false,
          },
          final_review: {
            stage: "final_review", actor_model_enabled: true, hard_floor_stage: true,
            human_signoff_required: true, source: "stage_contract", authorization_evaluated: false,
          },
          present_state: {
            gate_status: "open", outcome: state.outcomes[slot] ?? null,
            governed_head: { topic: 2, script: 3 },
          },
          production_direction: {
            pinned: { present: false }, observed: { present: false }, status: "not_yet_recorded",
          },
          classifications: {
            agent_execution: "not_applicable", agent_rep_delegation: "not_applicable",
            provider_operation: "not_applicable", secret_authority: "not_applicable",
          },
        },
        denials: available
          ? []
          : [{
              code: "signoff_blocked",
              detail: "the present decision outcome is 'pending', which is not an actionable approved state",
            }],
      });
    }
    if (p.endsWith("/final-review-projection")) {
      const slot = p.split("/")[3];
      return json(route, {
        gate_id: GATE, slot_id: slot, available: true, status: "recorded",
        target_identity: { gate_id: GATE, slot_id: slot, gate_stage: "final_review",
          gate_status: "open", admitted: true },
        package: null, assignment: null, decision_evidence: null,
        audit_evidence: { scope: "gate", slot_attributable: false, status: "gate_scoped_history",
          reasons: [], events: [] },
        uncertainty: [],
      });
    }
    if (p === "health") return json(route, { ok: true });
    // Anything unstubbed answers like the real seam's typed failure rather than an empty success.
    return json(route, { detail: `unstubbed read: ${p}` }, 503);
  });

  return { state, sent };
}

async function openFinalReview(page: Page) {
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=final_review`);
}

test.describe("R1 Stage 4 — Final Review reachability is derived from the governed artifact", () => {
  test("reachable from the run workspace when the governed generation enables the stage", async ({ page }) => {
    await installServer(page, { finalReview: "enabled" });
    await openFinalReview(page);

    // The rail carries the GOVERNED label; V2 authors none.
    await expect(page.getByRole("button", { name: "Publish approval" })).toBeVisible();
    // The workspace resolved to the canonical gate and rendered the Final Review panel.
    await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-gate-stage", "final_review");
    await expect(page.getByTestId("stage-panel-final_review")).toBeVisible();
    const ws = page.getByTestId("final-review-workspace");
    await expect(ws).toHaveAttribute("data-gate-id", GATE);
    await expect(ws).toHaveAttribute("data-lifecycle-state", "reviewing");
  });

  test("NOT actionable when the governed generation disables the stage", async ({ page }) => {
    await installServer(page, { finalReview: "disabled" });
    await openFinalReview(page);
    // The stage rail shows it truthfully disabled with the governed reason, and no panel renders.
    await expect(page.getByTestId("stage-panel-final_review")).toHaveCount(0);
    await expect(page.getByTestId("final-review-workspace")).toHaveCount(0);
  });

  test("ABSENT when the governed generation does not declare the stage at all", async ({ page }) => {
    await installServer(page, { finalReview: "absent" });
    await openFinalReviewSafe(page);
    await expect(page.getByRole("button", { name: "Publish approval" })).toHaveCount(0);
    await expect(page.getByTestId("final-review-workspace")).toHaveCount(0);
  });

  test("no active gate is a truthful state, never an empty item list", async ({ page }) => {
    await installServer(page, { state: { gateId: null } });
    await openFinalReview(page);
    await expect(page.getByTestId("final-review-no-gate")).toBeVisible();
    await expect(page.getByTestId("final-review-target")).toHaveCount(0);
    await expect(page.getByTestId("final-review-decision")).toHaveCount(0);
  });
});

/** `?stage=final_review` is canonicalized away by the shell when the artifact omits the stage, so the
 *  goto must not assert on the panel. Wrapped for readability of the intent. */
async function openFinalReviewSafe(page: Page) {
  await page.goto(`${WB_URL}/runs/${ROUND}?stage=final_review`);
  await expect(page.getByTestId("run-workspace")).toBeVisible();
}

test.describe("R1 Stage 4 — exact target propagation and the absence of client authority", () => {
  test("the decision carries the EXACT gate/slot and the SERVER-AUTHORED revision, and no actor", async ({ page }) => {
    const { sent } = await installServer(page);
    await openFinalReview(page);

    await expect(page.getByTestId("final-review-decision")).toHaveAttribute("data-offered", "true");
    await expect(page.getByTestId("final-review-decision-revision")).toHaveText("3");
    await page.getByTestId("final-review-decide").click();
    await expect(page.getByTestId("final-review-decide-result")).toHaveAttribute("data-result-kind", "accepted");
    // `engine.decide` returns the LIST of slot ids it recorded over, and the surface renders that
    // list — not a count it invented. Pinned because an integer-shaped classifier would have called
    // the real canonical success "contract drift".
    await expect(page.getByTestId("final-review-decide-touched")).toHaveAttribute("data-touched-count", "1");
    await expect(page.getByTestId("final-review-decide-touched")).toContainText(SLOT_A);

    const decide = sent.filter((s) => s.url === `gates/${GATE}/decide`);
    expect(decide, "exactly one decision request").toHaveLength(1);
    const body = decide[0].body as Record<string, unknown>;
    // The gate travels in the PATH; the slot and the server-authored revision travel in the body.
    expect(body.slot_ids, "scoped to the EXACT canonical target, never a whole-batch action")
      .toEqual([SLOT_A]);
    expect(body.revision, "the server-authored script_revision, forwarded verbatim").toBe(3);
    expect(body.decision).toBe("approve");
    // The decisive negative: nothing by which a client could assert identity or authority.
    for (const forbidden of ["actor", "approver_id", "principal", "principal_id", "role",
      "assignment", "quorum", "authority", "eligibility", "auto_advance", "advancement_mode"]) {
      expect(body, `the decide body must never carry ${forbidden}`).not.toHaveProperty(forbidden);
    }
    expect(Object.keys(body).sort()).toEqual(["decision", "revision", "slot_ids"]);
  });

  test("no decision is offered without a complete server-authored package tuple", async ({ page }) => {
    await installServer(page, { tuple: null });
    await openFinalReview(page);
    const block = page.getByTestId("final-review-decision");
    await expect(block).toHaveAttribute("data-offered", "false");
    await expect(block).toHaveAttribute("data-offer-reason", "no_complete_tuple");
    await expect(page.getByTestId("final-review-decide")).toHaveCount(0);
  });

  test("no decision is offered when the tuple identifies a different target", async ({ page }) => {
    await installServer(page, {
      tuple: { gate_id: GATE, slot_id: "SOME-OTHER-SLOT", snapshot_id: SNAP, topic_revision: 2,
        script_revision: 3, workflow_version_id: WF },
    });
    await openFinalReview(page);
    await expect(page.getByTestId("final-review-decision"))
      .toHaveAttribute("data-offer-reason", "target_mismatch");
    await expect(page.getByTestId("final-review-decide")).toHaveCount(0);
  });
});

test.describe("R1 Stage 4 — the canonical successful order is the one the surface presents", () => {
  // The backend requires decision -> sign-off -> resolve: `engine.sign_off` revalidates present
  // authority and refuses with `signoff_blocked` until an authoritative approved decision exists.
  // These cases pin that the surface teaches that order rather than an unachievable one.

  test("the steps appear in canonical order: inspect -> decision -> evidence -> transition", async ({ page }) => {
    await installServer(page);
    await openFinalReview(page);
    // The blocks live inside the selected item; wait for it rather than racing the mount.
    await expect(page.getByTestId("final-review-item")).toBeVisible();
    await expect(page.getByTestId("final-review-advance")).toBeVisible();
    const order = await page.evaluate(() => {
      const ids = ["final-review-inspect", "final-review-decision", "final-review-evidence",
        "final-review-advance"];
      return ids
        .map((id) => ({ id, el: document.querySelector(`[data-testid="${id}"]`) }))
        .filter((x) => x.el)
        // documentPosition orders the nodes as the operator meets them down the page.
        .sort((a, b) =>
          a.el!.compareDocumentPosition(b.el!) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1)
        .map((x) => x.id);
    });
    expect(order, "authority must precede evidence, and the transition must come last").toEqual([
      "final-review-inspect",
      "final-review-decision",
      "final-review-evidence",
      "final-review-advance",
    ]);
  });

  test("sign-off is NOT independently actionable before an approved outcome exists", async ({ page }) => {
    // Server truth: outcome pending -> preflight `signoff_blocked` -> no submit control at all.
    const { sent } = await installServer(page, {
      state: { outcomes: { [SLOT_A]: "pending", [SLOT_B]: "pending" } },
    });
    await openFinalReview(page);

    await expect(page.getByTestId("final-review-decision")).toHaveAttribute("data-offered", "true");
    const evidence = page.getByTestId("final-review-evidence");
    await expect(page.getByTestId("signoff-submit")).toHaveCount(0);
    // The reason shown is the SERVER's, relayed — the surface states no precondition of its own.
    await expect(evidence).toContainText("does not report this package as presently attemptable");
    await expect(page.locator('[data-reason="signoff_blocked"]').first()).toBeVisible();
    expect(sent, "nothing is attempted while the server reports the target blocked").toHaveLength(0);
  });

  test("sign-off becomes attemptable once the SERVER reports an approved outcome", async ({ page }) => {
    const { state } = await installServer(page, {
      state: { outcomes: { [SLOT_A]: "pending", [SLOT_B]: "pending" } },
    });
    await openFinalReview(page);
    await expect(page.getByTestId("signoff-submit")).toHaveCount(0);

    // Record the canonical decision. The stubbed server applies the outcome, as the real one does.
    await page.getByTestId("final-review-decide").click();
    await expect(page.getByTestId("final-review-decide-result"))
      .toHaveAttribute("data-result-kind", "accepted");
    // The refetch has landed and the SERVER now reports the approved outcome…
    await expect(page.getByTestId("final-review-target").first())
      .toHaveAttribute("data-current-outcome", "approved");

    // …so the preflight is re-read and the SERVER — not this surface — opens the control.
    await expect(page.getByTestId("signoff-submit")).toBeVisible();
  });
});

test.describe("R1 Stage 4 — sign-off is EVIDENCE ONLY and advances nothing", () => {
  test("recording sign-off issues NO decision and NO transition request", async ({ page }) => {
    // Models the state the canonical order reaches: the decision is recorded and the server-authorized
    // outcome permits sign-off. The point under test is what sign-off does NOT do from there.
    const { sent } = await installServer(page, {
      state: { lifecycle: "reviewing", outcomes: { [SLOT_A]: "approved", [SLOT_B]: "pending" } },
    });
    await openFinalReview(page);

    // The sign-off surface is reachable in-workspace and its submit exists.
    const submit = page.getByTestId("final-review-evidence").getByRole("button", { name: /sign[- ]off/i });
    await expect(submit.first()).toBeVisible();
    await submit.first().click();

    // Wait for the sign-off POST to have been issued and answered.
    await expect.poll(() => sent.filter((s) => s.url.endsWith("/sign-off")).length).toBe(1);

    // THE ASSERTION THIS WHOLE SUITE EXISTS FOR: evidence triggered no authority call of any kind.
    expect(sent.filter((s) => s.url.endsWith("/decide")),
      "sign-off must never cause a governed decision").toHaveLength(0);
    expect(sent.filter((s) => s.url.endsWith("/resolve")),
      "sign-off must never cause a lifecycle transition").toHaveLength(0);

    // And the lifecycle state the surface displays is unchanged — no optimistic advance.
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "reviewing");
    // The server-authored outcome is UNCHANGED by the sign-off — evidence moved nothing.
    await expect(page.getByTestId("final-review-target").first())
      .toHaveAttribute("data-current-outcome", "approved");
  });
});

test.describe("R1 Stage 4 — decision-before-resolve, manual advancement, no optimistic transition", () => {
  test("the transition is NOT offered while the server reports no recorded decision", async ({ page }) => {
    await installServer(page, { state: { outcomes: { [SLOT_A]: "pending", [SLOT_B]: "pending" } } });
    await openFinalReview(page);
    const advance = page.getByTestId("final-review-advance");
    await expect(advance).toHaveAttribute("data-offered", "false");
    await expect(advance).toHaveAttribute("data-offer-reason", "no_decision_recorded");
    await expect(page.getByTestId("final-review-resolve")).toHaveCount(0);
  });

  test("a recorded decision does NOT advance; the transition stays a separate explicit gesture", async ({ page }) => {
    const { state, sent } = await installServer(page);
    await openFinalReview(page);

    // Model the server recording the decision, exactly as the canonical command would.
    await page.getByTestId("final-review-decide").click();
    await expect(page.getByTestId("final-review-decide-result"))
      .toHaveAttribute("data-result-kind", "accepted");

    // The panel re-read the server and now shows the SERVER's outcome — it did not write one locally.
    await expect(page.getByTestId("final-review-target").first())
      .toHaveAttribute("data-current-outcome", "approved");
    // A decision is not a transition: the lifecycle state has not moved and no resolve was sent.
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "reviewing");
    expect(sent.filter((s) => s.url.endsWith("/resolve")),
      "a decision must never auto-invoke the transition").toHaveLength(0);

    // Only NOW is the transition offered, and only because the SERVER reported a decision.
    await expect(page.getByTestId("final-review-advance")).toHaveAttribute("data-offered", "true");
  });

  test("the explicit transition applies through the canonical path and the surface re-reads the server", async ({ page }) => {
    const { state, sent } = await installServer(page, {
      state: { outcomes: { [SLOT_A]: "approved", [SLOT_B]: "pending" } },
    });
    await openFinalReview(page);

    await expect(page.getByTestId("final-review-advance")).toHaveAttribute("data-offered", "true");
    // Model the server having transitioned when resolve is called.
    state.lifecycle = "complete";
    state.advanced = 1;
    await page.getByTestId("final-review-resolve").click();

    await expect(page.getByTestId("final-review-resolve-result"))
      .toHaveAttribute("data-result-kind", "accepted");
    const resolves = sent.filter((s) => s.url === `gates/${GATE}/resolve`);
    expect(resolves, "exactly one transition request").toHaveLength(1);
    expect((resolves[0].body as Record<string, unknown>).slot_ids).toEqual([SLOT_A]);
    expect(Object.keys(resolves[0].body as Record<string, unknown>),
      "the resolve body carries the target and no actor").toEqual(["slot_ids"]);

    // The authoritative state shown is the one the server returned on the REFETCH.
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "complete");
  });

  test("the transition ledger SURVIVES the advanced target leaving the gate", async ({ page }) => {
    // The live lane caught this: a successful transition moves the slot to the governed `approve_to`,
    // so on the next read it is no longer a target of this gate and the item unmounts. When the result
    // lived inside the item it vanished with it — at the exact moment the surface most needs to report
    // what the authority did. The ledger is therefore held at GATE level.
    const { state } = await installServer(page, {
      state: { outcomes: { [SLOT_A]: "approved", [SLOT_B]: "pending" } },
    });
    await openFinalReview(page);
    await expect(page.getByTestId("final-review-advance")).toHaveAttribute("data-offered", "true");

    // Model the server advancing SLOT_A out of the gate entirely, exactly as `engine.resolve` does.
    state.lifecycle = "reviewing";
    state.advanced = 1;
    delete (state.outcomes as Record<string, Outcome>)[SLOT_A];
    await page.getByTestId("final-review-resolve").click();

    // The target is gone from the server's list…
    await expect(page.getByTestId("final-review-target")).toHaveCount(1);
    // …and the server's own per-slot ledger is STILL on screen, attributed to the right slot.
    const record = page.getByTestId("final-review-transition-record");
    await expect(record).toHaveAttribute("data-slot-id", SLOT_A);
    await expect(page.getByTestId("final-review-resolve-result"))
      .toHaveAttribute("data-result-kind", "accepted");
    await expect(page.getByTestId("final-review-resolve-outcome").first())
      .toHaveAttribute("data-outcome", "approved");
  });

  test("a REFUSED transition never renders as an advance", async ({ page }) => {
    await installServer(page, {
      state: { outcomes: { [SLOT_A]: "approved", [SLOT_B]: "pending" } },
      onResolve: (route) => route.fulfill({
        status: 409, contentType: "application/json",
        body: JSON.stringify({ detail: "gate is resolved — not open" }),
      }),
    });
    await openFinalReview(page);
    await page.getByTestId("final-review-resolve").click();

    const result = page.getByTestId("final-review-resolve-result");
    await expect(result).toHaveAttribute("data-result-kind", "refused");
    // The server's own words, relayed verbatim, and no lifecycle movement whatsoever.
    await expect(result).toContainText("gate is resolved — not open");
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "reviewing");
    await expect(page.getByTestId("final-review-resolve-outcomes")).toHaveCount(0);
  });

  test("a seam refusal is never rendered as an authority denial", async ({ page }) => {
    await installServer(page, {
      state: { outcomes: { [SLOT_A]: "approved", [SLOT_B]: "pending" } },
      onResolve: (route) => route.fulfill({
        status: 501, contentType: "application/json",
        body: JSON.stringify({ detail: "workbench (V2) writes only in an explicit local/dev/test runtime" }),
      }),
    });
    await openFinalReview(page);
    await page.getByTestId("final-review-resolve").click();
    const result = page.getByTestId("final-review-resolve-result");
    await expect(result).toHaveAttribute("data-result-kind", "seam_refusal");
    await expect(result).toContainText("never reached");
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "reviewing");
  });

  test("a drifted success body is never rendered as an applied transition", async ({ page }) => {
    await installServer(page, {
      state: { outcomes: { [SLOT_A]: "approved", [SLOT_B]: "pending" } },
      onResolve: (route) => route.fulfill({
        status: 200, contentType: "application/json", body: JSON.stringify({ moved: true }),
      }),
    });
    await openFinalReview(page);
    await page.getByTestId("final-review-resolve").click();
    await expect(page.getByTestId("final-review-resolve-result"))
      .toHaveAttribute("data-result-kind", "contract_drift");
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "reviewing");
  });
});

test.describe("R1 Stage 4 — the authoritative state survives a reload", () => {
  test("a transitioned run renders the SAME server state after a full reload", async ({ page }) => {
    // The server is authoritative and already advanced. Nothing about this state is client-held.
    await installServer(page, {
      state: { lifecycle: "complete", advanced: 1, outcomes: { [SLOT_A]: "approved", [SLOT_B]: "approved" } },
    });
    await openFinalReview(page);
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "complete");

    await page.reload();
    await expect(page.getByTestId("final-review-workspace"))
      .toHaveAttribute("data-lifecycle-state", "complete");
    await expect(page.getByTestId("final-review-target").first())
      .toHaveAttribute("data-current-outcome", "approved");
  });

  test("a selected item is link- and reload-stable, and an unknown item falls back fail-closed", async ({ page }) => {
    await installServer(page);
    await page.goto(`${WB_URL}/runs/${ROUND}?stage=final_review&item=${SLOT_B}`);
    await expect(page.getByTestId("final-review-item")).toHaveAttribute("data-slot-id", SLOT_B);
    await page.reload();
    await expect(page.getByTestId("final-review-item")).toHaveAttribute("data-slot-id", SLOT_B);

    // An item the canonical gate does not govern never selects — it falls back to the first target.
    await page.goto(`${WB_URL}/runs/${ROUND}?stage=final_review&item=NOT-A-TARGET`);
    await expect(page.getByTestId("final-review-item")).toHaveAttribute("data-slot-id", SLOT_A);
  });
});
