"use client";

// #431 — read-only Stage 4 final-review projection surface for one (gate, slot).
//
// It renders the authoritative backend projection (GET /gates/{gate}/slots/{slot}/final-review-projection)
// VERBATIM. The backend is the SOLE authority for aggregation, evidence status, historical uncertainty,
// decision attribution, and audit scope: this panel performs NO join, NO coverage math, NO admission /
// attribution / authority inference, and NO reason-code reinterpretation. Every branch is driven by a
// typed backend field, never by prose.
//
// Fail-closed invariants held here:
//   • each evidence group renders INDEPENDENTLY, carrying its own typed status;
//   • immutable package evidence is shown as recorded history, never as current Topic/Script/workflow state;
//   • the governing assignment is shown as a GATE-WIDE frozen snapshot, never target-level;
//   • frozen eligibility is HISTORY, never present authorization;
//   • persisted decisions are EVIDENCE, never an approve/reject/sign-off opportunity;
//   • audit is GATE-scoped and never slot-attributable; missing audit is never "no activity";
//   • unknown / unavailable / inconsistent / ambiguous / legacy / incomplete stay visibly typed;
//   • raw principal IDs (eligible principals, covering principal, approver, audit actor) are WITHHELD
//     from identity presentation — only non-identifying structure (counts, coverage presence, decision
//     kind, revision, timestamp) is shown. No live IAM / directory / identity resolution.
// Only a transport/read failure offers retry; typed historical uncertainty never does.

import { useEffect, useState } from "react";
import { readJson, ReadError, type FinalReviewProjection } from "@/lib/read-model";
import { nullGroupPresentation } from "@/lib/final-review-presentation";

type Load =
  | { state: "loading" }
  | { state: "ok"; model: FinalReviewProjection }
  | { state: "error"; status: number; detail: string };

const WITHHELD = "identity withheld";

function StatusLine({ status }: { status: string }) {
  return (
    <p data-testid="frp-top-status" data-status={status}>
      <strong>Evidence status:</strong> <span data-status-value={status}>{status}</span>
    </p>
  );
}

function ReasonCodes({ testid, reasons }: { testid: string; reasons: string[] }) {
  if (!reasons.length) return null;
  return (
    <ul data-testid={testid}>
      {reasons.map((r) => (
        <li key={r} data-reason={r}>
          {r}
        </li>
      ))}
    </ul>
  );
}

export function FinalReviewProjectionPanel({ gateId, slotId }: { gateId: string; slotId: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  // Retries the READ ONLY (transport failure). Never used to "reconstruct" typed historical evidence.
  const [readNonce, setReadNonce] = useState(0);

  useEffect(() => {
    const ac = new AbortController();
    setLoad({ state: "loading" });
    readJson<FinalReviewProjection>(
      `/gw/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/final-review-projection`,
      ac.signal,
    )
      .then((model) => setLoad({ state: "ok", model }))
      .catch((e: unknown) => {
        if ((e as Error)?.name === "AbortError") return;
        const err = e as ReadError;
        setLoad({ state: "error", status: err?.status ?? 0, detail: err?.message ?? "read failed" });
      });
    return () => ac.abort();
  }, [gateId, slotId, readNonce]);

  if (load.state === "loading") {
    return (
      <section data-testid="final-review-projection" data-load="loading" aria-busy="true">
        <h1>Final-review projection</h1>
        <p>Loading recorded evidence…</p>
      </section>
    );
  }

  if (load.state === "error") {
    // Transport/read failure ONLY — distinct from a typed `unavailable` response. Retry is offered here
    // and nowhere else; it re-issues the read and cannot reconstruct historical evidence.
    return (
      <section data-testid="final-review-projection" data-load="error" data-status={load.status}>
        <h1>Final-review projection</h1>
        <p role="alert">Could not read the final-review projection: {load.detail}</p>
        <button type="button" data-testid="frp-retry" onClick={() => setReadNonce((n) => n + 1)}>
          Retry read
        </button>
      </section>
    );
  }

  const m = load.model;
  const pkg = m.package;
  const asg = m.assignment;
  const dec = m.decision_evidence;
  const aud = m.audit_evidence;

  // #433 — a NULL/absent group's presentation is derived ONLY from authoritative fields (top-level
  // status + any per-group status), never invented from the null itself. The package object may carry
  // its own `status` even when its `evidence` is null; assignment/decision are wholly null in their
  // absent branches, so only the top-level status categorises them.
  const pkgAbsent = nullGroupPresentation(m.status, pkg?.status);
  const asgAbsent = nullGroupPresentation(m.status);
  const decAbsent = nullGroupPresentation(m.status);

  return (
    <section
      data-testid="final-review-projection"
      data-load="ok"
      data-gate-id={m.gate_id}
      data-slot-id={m.slot_id}
      data-status={m.status}
      data-available={String(m.available)}
    >
      <h1>Final-review projection</h1>
      <StatusLine status={m.status} />
      <ReasonCodes testid="frp-uncertainty" reasons={m.uncertainty} />

      {/* ── Target identity ─────────────────────────────────────────────── */}
      <section data-testid="frp-identity" data-present={String(m.target_identity !== null)}>
        <h2>Target identity</h2>
        {m.target_identity ? (
          <dl>
            <dt>Gate</dt>
            <dd>{m.target_identity.gate_id}</dd>
            <dt>Slot</dt>
            <dd>{m.target_identity.slot_id}</dd>
            <dt>Gate stage</dt>
            <dd>{m.target_identity.gate_stage}</dd>
            {/* gate lifecycle STATUS is an evidence fact, not an action state */}
            <dt>Gate lifecycle status (evidence)</dt>
            <dd data-gate-status={m.target_identity.gate_status}>{m.target_identity.gate_status}</dd>
            <dt>Admitted target</dt>
            <dd>{String(m.target_identity.admitted)}</dd>
          </dl>
        ) : (
          <p data-testid="frp-identity-absent">
            No canonical gate identity for this pair — not an admitted final-review target.
          </p>
        )}
      </section>

      {/* ── Immutable attached target package (recorded history, NOT current artifact state) ── */}
      <section data-testid="frp-package" data-status={pkg?.status ?? "absent"}>
        <h2>Attached target package (immutable evidence)</h2>
        {pkg && pkg.evidence ? (
          <dl>
            <dt>Gate-wide frozen snapshot</dt>
            <dd>{pkg.evidence.snapshot_id}</dd>
            <dt>Round</dt>
            <dd>{pkg.evidence.round_id}</dd>
            <dt>Selected topic (as attached)</dt>
            <dd>
              {pkg.evidence.topic_id} rev {pkg.evidence.topic_revision}
            </dd>
            <dt>Selected script (as attached)</dt>
            <dd>
              {pkg.evidence.script_id} rev {pkg.evidence.script_revision}
            </dd>
            <dt>Consumed workflow version</dt>
            <dd>
              {pkg.evidence.workflow_version_id} ({pkg.evidence.workflow_version_source})
            </dd>
            <dt>Production direction (observed reference)</dt>
            <dd>
              {pkg.evidence.production_direction.present
                ? `present · directive ${pkg.evidence.production_direction.directive_id} rev ${pkg.evidence.production_direction.revision}`
                : "not recorded"}
            </dd>
            <dt>Attached at</dt>
            <dd>{pkg.evidence.attached_at}</dd>
          </dl>
        ) : (
          <p data-testid="frp-package-absent" data-category={pkgAbsent.category}>
            {pkgAbsent.copy}
          </p>
        )}
      </section>

      {/* ── Governing assignment: GATE-WIDE frozen snapshot (never target-level) ── */}
      <section data-testid="frp-assignment" data-present={String(asg !== null)}>
        <h2>Governing assignment (gate-wide frozen snapshot)</h2>
        {asg ? (
          <>
            <dl>
              <dt>Snapshot</dt>
              <dd>
                {asg.snapshot_id} (v{asg.snapshot_version ?? "—"})
              </dd>
              <dt>Opened at</dt>
              <dd>{asg.opened_at ?? "—"}</dd>
              <dt>Rule</dt>
              <dd>{asg.rule_key}</dd>
            </dl>
            <p data-testid="frp-eligibility-note">
              Frozen historical eligibility — recorded at gate-open. This is not present authorization,
              current membership, or a current ability to act.
            </p>
            <ul data-testid="frp-assignment-tokens">
              {asg.tokens.map((t) => (
                <li key={t.normalized_token} data-token={t.normalized_token}>
                  {t.normalized_token} —{" "}
                  <span data-eligible-count={t.eligible_principals.length}>
                    {t.eligible_principals.length} historically eligible principal
                    {t.eligible_principals.length === 1 ? "" : "s"} ({WITHHELD})
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p data-testid="frp-assignment-absent" data-category={asgAbsent.category}>
            {asgAbsent.copy}
          </p>
        )}
      </section>

      {/* ── Persisted decision + coverage evidence (EVIDENCE, never an action opportunity) ── */}
      <section data-testid="frp-decision" data-status={dec?.status ?? "absent"} data-recorded={String(dec?.recorded ?? false)}>
        <h2>Decision &amp; coverage evidence</h2>
        {dec ? (
          <>
            <ReasonCodes testid="frp-decision-reasons" reasons={dec.reasons} />
            <dl>
              <dt>Governing snapshot</dt>
              <dd>{dec.governing_snapshot_id}</dd>
              <dt>Recorded outcome (evidence value)</dt>
              <dd data-outcome={dec.outcome}>{dec.outcome}</dd>
              <dt>Approval count</dt>
              <dd>{dec.approval_count}</dd>
              <dt>Distinct-principal coverage</dt>
              <dd>{dec.distinct_principal_coverage}</dd>
            </dl>
            <ul data-testid="frp-coverage">
              {dec.coverage.map((c) => (
                <li key={c.normalized_token} data-token={c.normalized_token} data-covered={String(c.covered_by !== null)}>
                  {c.normalized_token} — {c.covered_by !== null ? `covered (${WITHHELD})` : "uncovered"}
                </li>
              ))}
            </ul>
            <ul data-testid="frp-decisions">
              {dec.decisions.map((d, i) => (
                <li key={`${d.decision}-${d.revision ?? "head"}-${i}`} data-decision={d.decision}>
                  {d.decision}
                  {d.revision !== null ? ` · rev ${d.revision}` : ""}
                  {d.decided_at ? ` · ${d.decided_at}` : ""} · approver {WITHHELD}
                </li>
              ))}
            </ul>
            <p data-testid="frp-decision-note">
              Recorded historical evidence only — not a new opportunity to approve, reject, sign off,
              reconsider, reopen, or rework.
            </p>
          </>
        ) : (
          <p data-testid="frp-decision-absent" data-category={decAbsent.category}>
            {decAbsent.copy}
          </p>
        )}
      </section>

      {/* ── Gate-scoped audit history — explicitly NON-slot-attributable ── */}
      <section
        data-testid="frp-audit"
        data-scope={aud?.scope ?? "absent"}
        data-slot-attributable={String(aud?.slot_attributable ?? false)}
        data-status={aud?.status ?? "absent"}
      >
        <h2>Audit history (gate-scoped)</h2>
        {aud ? (
          <>
            <p data-testid="frp-audit-scope-note">
              Scope: {aud.scope} · not slot-attributable. These are gate-level events, not evidence
              that this slot or target had activity, and not slot decision provenance.
            </p>
            <ReasonCodes testid="frp-audit-reasons" reasons={aud.reasons} />
            {aud.status === "gate_scoped_history" ? (
              <ul data-testid="frp-audit-events">
                {aud.events.map((e) => (
                  <li key={e.id} data-action={e.action}>
                    {e.action}
                    {e.at ? ` · ${e.at}` : ""}
                    {e.actor ? ` · actor ${WITHHELD}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <p data-testid="frp-audit-absent">
                No gate-scoped audit history recorded. This is not evidence that no activity occurred.
              </p>
            )}
          </>
        ) : (
          <p data-testid="frp-audit-absent">No audit group for this pair.</p>
        )}
      </section>
    </section>
  );
}
