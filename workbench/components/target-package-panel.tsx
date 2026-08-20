"use client";

// #423 — read-only final-review target-package evidence surface.
//
// Renders the server's typed recorded / unknown_history / unavailable verdict VERBATIM for one
// (gate, slot). It reconstructs nothing, offers no action, and is a pure read — a legacy target with
// no recorded package shows as unknown_history (never rebuilt from current state), and an attachment
// refusal can never appear here (that outcome comes only from the governed attachment path).

import { useEffect, useState } from "react";
import { readJson, ReadError, type TargetPackageEvidence } from "@/lib/read-model";

type Load =
  | { state: "loading" }
  | { state: "ok"; model: TargetPackageEvidence }
  | { state: "error"; status: number; detail: string };

export function TargetPackagePanel({ gateId, slotId }: { gateId: string; slotId: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    const ac = new AbortController();
    setLoad({ state: "loading" });
    readJson<TargetPackageEvidence>(
      `/gw/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/target-package`,
      ac.signal,
    )
      .then((model) => setLoad({ state: "ok", model }))
      .catch((e: unknown) => {
        if ((e as Error)?.name === "AbortError") return;
        const err = e as ReadError;
        setLoad({ state: "error", status: err?.status ?? 0, detail: err?.message ?? "read failed" });
      });
    return () => ac.abort();
  }, [gateId, slotId]);

  if (load.state === "loading") {
    return (
      <section data-testid="target-package" data-load="loading" aria-busy="true">
        <h1>Final-review target package</h1>
        <p>Loading recorded evidence…</p>
      </section>
    );
  }
  if (load.state === "error") {
    return (
      <section data-testid="target-package" data-load="error" data-status={load.status}>
        <h1>Final-review target package</h1>
        <p role="alert">Could not read the target-package evidence: {load.detail}</p>
      </section>
    );
  }

  const m = load.model;
  const ev = m.evidence;
  const label =
    m.status === "recorded" ? "Recorded" : m.status === "unknown_history" ? "Unknown history" : "Unavailable";
  return (
    <section
      data-testid="target-package"
      data-load="ok"
      data-gate-id={m.gate_id}
      data-slot-id={m.slot_id}
      data-status={m.status}
      data-recorded={String(m.recorded)}
    >
      <h1>Final-review target package</h1>
      <p data-testid="target-package-status">
        <strong>{label}</strong>
      </p>

      {ev ? (
        <dl>
          <dt>Gate-wide frozen snapshot</dt>
          <dd>{ev.snapshot_id}</dd>
          <dt>Round</dt>
          <dd>{ev.round_id}</dd>
          <dt>Selected topic</dt>
          <dd>
            {ev.topic_id} rev {ev.topic_revision}
          </dd>
          <dt>Selected script</dt>
          <dd>
            {ev.script_id} rev {ev.script_revision}
          </dd>
          <dt>Consumed workflow version</dt>
          <dd data-testid="target-package-workflow">
            {ev.workflow_version_id} ({ev.workflow_version_source})
          </dd>
          <dt>Production direction (observed)</dt>
          <dd data-testid="target-package-direction">
            {ev.production_direction.present
              ? `present · directive ${ev.production_direction.directive_id} rev ${ev.production_direction.revision}`
              : "not recorded"}
          </dd>
          <dt>Attached at</dt>
          <dd>{ev.attached_at}</dd>
        </dl>
      ) : (
        <p data-testid="target-package-absent">
          {m.status === "unknown_history"
            ? "No package evidence was recorded for this target (it was attached before this evidence existed). It is deliberately not reconstructed from current selections, membership, the active workflow, or labels."
            : "This gate/slot pair is not a recorded gate target."}
        </p>
      )}
    </section>
  );
}
