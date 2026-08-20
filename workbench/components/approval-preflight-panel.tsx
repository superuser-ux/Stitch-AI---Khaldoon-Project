"use client";

// #447 — read-only Stage 4 approval-package preflight surface for one (gate, slot).
//
// It renders the authoritative backend read model (GET /gates/{gate}/slots/{slot}/approval-preflight)
// VERBATIM. The backend is the SOLE authority for pinning, coherence, eligibility, authority, and
// reason precedence: this panel performs NO join, NO lineage reconstruction, NO coverage math, NO
// re-ranking of denials, and NO reason-code reinterpretation. Every branch is driven by a typed
// backend field, never by prose.
//
// Fail-closed invariants held here:
//   • the six-member tuple is shown ONLY when the server returned all six — a partial pin is never
//     assembled, padded, or displayed (enforced in lib/approval-preflight-presentation.ts);
//   • `available` (eligibility verdict) and `status` (historical evidence) stay DISTINCT and are
//     never collapsed into one another;
//   • the pinned workflow version is EVIDENCE; the active version is a coherence check. Neither is
//     ever substituted for the other, and divergence is the server's denial, not a local judgement;
//   • the human hard floor is a STRUCTURAL stage requirement, never a permission. No principal is
//     evaluated anywhere in this slice, and no identity is displayed because the server sends none;
//   • the production direction is downstream EVIDENCE only — never approval, sign-off, lifecycle
//     advancement, or authorization to execute Production;
//   • this surface performs NO action. It cannot sign off, approve, decide, advance, or execute
//     anything. Its only interactive controls are a retry for a transport failure and — since #449 —
//     a NAVIGATION LINK to the sign-off action route. That link is not an action: it signs nothing,
//     sends nothing, and mutates nothing. It is rendered ONLY when the server-authored `available`
//     verdict is true, so an ineligible target is not given a reachable action surface at all, and it
//     is never labelled authorized, permitted, ready, or guaranteed to succeed.
// Only a transport/read failure offers retry; a typed denial or unknown history never does.

import { useEffect, useState } from "react";
import Link from "next/link";
import { readJson, ReadError, type ApprovalPreflight } from "@/lib/read-model";
import {
  humanAuthorityCopy,
  preflightVerdict,
  tuplePresentation,
} from "@/lib/approval-preflight-presentation";

type Load =
  | { state: "loading" }
  | { state: "ok"; model: ApprovalPreflight }
  | { state: "error"; status: number; detail: string };

function Row({ label, value }: { label: string; value: string }) {
  return (
    <p>
      <strong>{label}:</strong> <span>{value}</span>
    </p>
  );
}

export function ApprovalPreflightPanel({ gateId, slotId }: { gateId: string; slotId: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  // Retries the READ ONLY (transport failure). Never used to "reconstruct" a typed server result.
  const [readNonce, setReadNonce] = useState(0);

  useEffect(() => {
    const ac = new AbortController();
    setLoad({ state: "loading" });
    readJson<ApprovalPreflight>(
      `/gw/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/approval-preflight`,
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
      <section data-testid="approval-preflight" data-load="loading" aria-busy="true">
        <h1>Approval-package preflight</h1>
        <p>Loading recorded evidence…</p>
      </section>
    );
  }

  if (load.state === "error") {
    // Transport/read failure ONLY — distinct from a typed `unavailable` response. Retry is offered
    // here and nowhere else; it re-issues the read and cannot reconstruct server truth.
    return (
      <section data-testid="approval-preflight" data-load="error" data-status={load.status}>
        <h1>Approval-package preflight</h1>
        <p role="alert">Could not read the approval preflight: {load.detail}</p>
        <button type="button" data-testid="apf-retry" onClick={() => setReadNonce((n) => n + 1)}>
          Retry read
        </button>
      </section>
    );
  }

  const model = load.model;
  const verdict = preflightVerdict(model);
  const tuple = tuplePresentation(model.target_package_tuple);
  const ev = model.evidence;

  return (
    <section
      data-testid="approval-preflight"
      data-load="ok"
      data-category={verdict.category}
      data-available={String(model.available)}
      data-evidence-status={model.status}
    >
      <h1>Approval-package preflight</h1>

      {/* Eligibility verdict and historical evidence status are shown as SEPARATE facts. */}
      <p data-testid="apf-verdict" data-category={verdict.category}>
        {verdict.copy}
      </p>
      <Row label="Eligibility" value={model.available ? "eligible" : "not eligible"} />
      <Row label="Evidence status" value={model.status} />
      {verdict.primaryReason ? (
        <p data-testid="apf-primary-reason" data-reason={verdict.primaryReason}>
          <strong>Primary reason:</strong> <span>{verdict.primaryReason}</span>
        </p>
      ) : null}

      {/* #449 — the entry affordance to the sign-off action route. NAVIGATION ONLY: it signs nothing,
          sends nothing, and mutates nothing. Gated on the server-authored `available` verdict alone,
          so an ineligible target has no reachable action surface; the copy states attemptability, not
          permission, and promises no outcome. */}
      {model.available ? (
        <p>
          <Link
            data-testid="apf-signoff-entry"
            href={`/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/sign-off`}
          >
            Open the final-review sign-off request
          </Link>
          <span> — the server revalidates present state and authority when the command runs.</span>
        </p>
      ) : null}

      {/* The six-member tuple — all six, or an explicit withheld statement. Never partial. */}
      <h2>Immutable package tuple</h2>
      {tuple.complete ? (
        <dl data-testid="apf-tuple" data-complete="true">
          {tuple.members.map((m) => (
            <div key={m.key} data-member={m.key}>
              <dt>{m.key}</dt>
              <dd>{m.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p data-testid="apf-tuple" data-complete="false">
          The server did not return a complete six-member package tuple. A partially pinned package is
          never shown.
        </p>
      )}

      {/* Pinned is evidence; active is the coherence check. Never substituted for one another. */}
      <h2>Governed workflow version</h2>
      <div data-testid="apf-workflow" data-divergent={String(ev.workflow.divergent)}>
        <Row
          label="Pinned by the package"
          value={
            ev.workflow.pinned
              ? `${ev.workflow.pinned.version_id} (source: ${ev.workflow.pinned.source})`
              : "not supplied"
          }
        />
        <Row
          label="Currently active"
          value={
            ev.workflow.active && "version_id" in ev.workflow.active
              ? ev.workflow.active.version_id
              : (ev.workflow.active?.status ?? "not supplied")
          }
        />
      </div>

      {/* STRUCTURAL hard floor only. No principal is evaluated or displayed. */}
      <h2>Human authority</h2>
      <p data-testid="apf-authority" data-required={String(ev.final_review?.human_signoff_required)}>
        {humanAuthorityCopy(ev.final_review)}
      </p>

      <h2>Present state</h2>
      <div data-testid="apf-present-state">
        <Row label="Gate status" value={ev.present_state?.gate_status ?? "not supplied"} />
        <Row label="Decision outcome" value={ev.present_state?.outcome ?? "not supplied"} />
        <Row
          label="Governed head (topic / script)"
          value={`${ev.present_state?.governed_head.topic ?? "—"} / ${
            ev.present_state?.governed_head.script ?? "—"
          }`}
        />
      </div>

      {/* Downstream EVIDENCE only — never approval, sign-off, or authorization to execute Production. */}
      <h2>Script-to-Production direction</h2>
      <div data-testid="apf-direction" data-status={ev.production_direction?.status ?? "not_supplied"}>
        <Row label="Status" value={ev.production_direction?.status ?? "not supplied"} />
        <Row
          label="Pinned by the package"
          value={ev.production_direction?.pinned.present ? "present" : "not present"}
        />
        <Row
          label="Observed in canonical state"
          value={ev.production_direction?.observed.present ? "present" : "not present"}
        />
        <p>Evidence only. It is not approval, sign-off, lifecycle advancement, or authorization to execute Production.</p>
      </div>

      {/* Server-authored denials, rendered in the server's precedence order. Never re-sorted. */}
      {model.denials.length ? (
        <>
          <h2>Server-authored reasons</h2>
          <ol data-testid="apf-denials">
            {model.denials.map((d) => (
              <li key={d.code} data-reason={d.code}>
                <strong>{d.code}</strong> — {d.detail}
              </li>
            ))}
          </ol>
        </>
      ) : null}

      <h2>Classifications</h2>
      <dl data-testid="apf-classifications">
        {Object.entries(ev.classifications).map(([k, v]) => (
          <div key={k} data-classification={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
