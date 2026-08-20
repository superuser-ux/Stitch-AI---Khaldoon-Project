"use client";

// #419 — read-only Stage 4 approval-package preflight surface.
//
// It renders the SERVER'S typed verdict verbatim (`available`, `reason_code`, `detail`, structured
// `evidence`, and the full `denials` list) and reconstructs nothing. Consumed vs active workflow
// identity are shown as distinct facts; a divergence or any missing/underivable pin appears as a
// fail-closed denial. It offers NO action and never implies a denied/unavailable path exists — it is
// purely a truthful read of whether one canonical Schedule → Topic → Script package is coherent and
// eligible for human final review / production direction.

import { useEffect, useState } from "react";
import { readJson, ReadError, type Stage4Preflight, type Stage4WorkflowIdentity } from "@/lib/read-model";

type Load =
  | { state: "loading" }
  | { state: "ok"; model: Stage4Preflight }
  | { state: "error"; status: number; detail: string };

function wfLabel(w: Stage4WorkflowIdentity | null): string {
  if (!w) return "—";
  if ("version_id" in w) return `${w.version_id}${w.source ? ` (${w.source})` : ""}`;
  return w.status;
}

export function Stage4PreflightPanel({ slotId }: { slotId: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    const ac = new AbortController();
    setLoad({ state: "loading" });
    readJson<Stage4Preflight>(
      `/gw/slots/${encodeURIComponent(slotId)}/stage4_preflight`,
      ac.signal,
    )
      .then((model) => setLoad({ state: "ok", model }))
      .catch((e: unknown) => {
        if ((e as Error)?.name === "AbortError") return;
        const err = e as ReadError;
        setLoad({ state: "error", status: err?.status ?? 0, detail: err?.message ?? "read failed" });
      });
    return () => ac.abort();
  }, [slotId]);

  if (load.state === "loading") {
    return (
      <section data-testid="stage4-preflight" data-load="loading" aria-busy="true">
        <h1>Stage 4 package preflight</h1>
        <p>Loading server-authoritative preflight for slot {slotId}…</p>
      </section>
    );
  }

  if (load.state === "error") {
    // A failed read is surfaced honestly — never collapsed into an empty "eligible" success.
    return (
      <section data-testid="stage4-preflight" data-load="error" data-status={load.status}>
        <h1>Stage 4 package preflight</h1>
        <p role="alert">Could not read the preflight: {load.detail}</p>
      </section>
    );
  }

  const m = load.model;
  const ev = m.evidence;
  return (
    <section
      data-testid="stage4-preflight"
      data-load="ok"
      data-slot-id={m.candidate.slot_id}
      data-available={String(m.available)}
      data-reason-code={m.reason_code}
    >
      <h1>Stage 4 package preflight</h1>

      <p data-testid="stage4-verdict">
        <strong>{m.available ? "Eligible for human final review" : "Not eligible"}</strong>
        {" — "}
        <span data-testid="stage4-reason-code">{m.reason_code}</span>
      </p>
      {/* Server detail is display-only; never parsed for readiness/lineage. */}
      <p data-testid="stage4-detail">{m.detail}</p>

      <dl>
        <dt>Schedule</dt>
        <dd>
          {ev.schedule
            ? `slot ${ev.schedule.slot_id} · round ${ev.schedule.round_id} · ${ev.schedule.status}`
            : "—"}
        </dd>

        <dt>Selected topic</dt>
        <dd>{ev.topic ? `${ev.topic.topic_id} rev ${ev.topic.revision}` : "—"}</dd>

        <dt>Selected script</dt>
        <dd>{ev.script ? `${ev.script.script_id} rev ${ev.script.revision}` : "—"}</dd>

        {/* Consumed vs active are DISTINCT facts, shown side by side; divergence is explicit. */}
        <dt>Consumed workflow version</dt>
        <dd data-testid="stage4-consumed-workflow">{wfLabel(ev.workflow.consumed)}</dd>
        <dt>Active workflow version</dt>
        <dd data-testid="stage4-active-workflow">{wfLabel(ev.workflow.active)}</dd>
        <dt>Consumed ≠ active</dt>
        <dd data-testid="stage4-divergent">
          {ev.workflow.divergent === null ? "—" : String(ev.workflow.divergent)}
        </dd>

        <dt>Consumed generation versions</dt>
        <dd>
          {ev.consumed_versions
            ? `methodology ${ev.consumed_versions.methodology_version ?? "unknown"} · ` +
              `content-format ${ev.consumed_versions.content_format_version ?? "unknown"} · ` +
              `framework ${ev.consumed_versions.framework_version ?? "unknown"} · ` +
              `writer-contract ${ev.consumed_versions.writer_contract_version ?? "unknown"}`
            : "unknown"}
        </dd>

        <dt>Final review</dt>
        <dd data-testid="stage4-final-review">
          {ev.final_review && "required" in ev.final_review
            ? `human-required: ${String(ev.final_review.human_required)} · rule ` +
              `${ev.final_review.approval_rule} · from consumed version ${ev.final_review.source_version_id}`
            : "unknown"}
        </dd>

        <dt>Production direction (observed)</dt>
        <dd
          data-testid="stage4-production-direction"
          data-direction-status={
            ev.production_direction.status ?? (ev.production_direction.present ? "present" : "")
          }
        >
          {!ev.production_direction.present
            ? "not yet recorded (recorded at/after human final review)"
            : ev.production_direction.status === "malformed"
              ? "malformed (fail-closed)"
              : ev.production_direction.status === "mismatch"
                ? `mismatch (rev ${ev.production_direction.revision}, expected ${ev.production_direction.expected_revision}) — fail-closed`
                : `present · directive ${ev.production_direction.directive_id} rev ${ev.production_direction.revision}`}
        </dd>

        <dt>Capability / authority classifications</dt>
        <dd>
          {`agent ${ev.classifications.agent_execution} · agent-rep ${ev.classifications.agent_rep_delegation} · ` +
            `provider ${ev.classifications.provider_operation} · secret ${ev.classifications.secret_authority}`}
        </dd>
      </dl>

      {m.denials.length > 0 && (
        <div data-testid="stage4-denials">
          <h2>Server-authored reasons</h2>
          <ul>
            {m.denials.map((d) => (
              <li key={d.code} data-denial-code={d.code}>
                <code>{d.code}</code>: {d.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
