"use client";

// #449 — the V2 final-review SIGN-OFF action surface for one (gate, slot).
//
// This is the ONLY action in the Stage 4 V2 lane, and it is deliberately thin. It reads the
// server-authored #447/#448 preflight, forwards the four immutable binding fields VERBATIM to the
// merged #439/#440 command, and renders whatever the server says. It decides nothing.
//
// Fail-closed invariants held here:
//   • the submit control exists ONLY when the server-authored preflight reports the target
//     attemptable AND the six-member tuple is complete AND its target matches this route — otherwise
//     no control is rendered at all (lib/sign-off-action.ts owns that decision);
//   • "attemptable" is never presented as authorized, permitted, ready, or guaranteed. The command
//     revalidates present state and authority when it runs and can still refuse;
//   • the opaque idempotency value is minted LAZILY on first submit, scoped to the exact tuple,
//     discarded when the tuple changes, and reused ONLY for an identical TRANSPORT retry — the single
//     case where the request produced no response at all, which is what turns a retry over an
//     already-committed receipt into the ORIGINAL receipt instead of a fabricated
//     `signoff_already_recorded`. It is discarded after any other result, so a seam refusal (503
//     included) never re-sends under the same value;
//   • a seam refusal, a transport failure, and a server outcome are rendered as THREE DISTINCT facts;
//   • no lifecycle transition is ever applied optimistically. This surface advances nothing, and after
//     any result it points back at the server's own preflight rather than mutating local state;
//   • no principal is displayed or inferred anywhere: the /gw route signs its own principal
//     server-side and the preflight discloses none.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  postJson,
  readJson,
  ReadError,
  WriteError,
  type ApprovalPreflight,
  type SignOffReceipt,
} from "@/lib/read-model";
import {
  ATTEMPTABILITY_COPY,
  attemptability,
  classifyFailure,
  classifySuccess,
  isRetryable,
  nonOutcomeCopy,
  OUTCOME_COPY,
  RECEIPT_MEMBERS,
  signOffPath,
  signOffRequest,
  tupleIdentity,
  type SignOffResult,
} from "@/lib/sign-off-action";

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

function Receipt({ receipt }: { receipt: SignOffReceipt }) {
  // The receipt is server-authored EVIDENCE that a sign-off is recorded. It is rendered VERBATIM —
  // all TEN canonical members of `engine._signoff_receipt`, in the server's own order, including the
  // canonical `operation`. Rendering a subset while claiming verbatim would be a quiet edit of server
  // truth; `classifySuccess` refuses anything short of the complete shape, so the two agree.
  // No lifecycle, approval, or authority conclusion is drawn from any of it here.
  // Rows are DERIVED from the same canonical membership `classifySuccess` validates, so the rendered
  // receipt and the accepted receipt can never disagree. A hand-maintained row list is what let
  // `operation` go missing while this comment claimed verbatim; deriving makes that class of drift
  // structurally impossible rather than a thing to remember.
  return (
    <dl data-testid="signoff-receipt">
      {RECEIPT_MEMBERS.map((member) => (
        <div key={member} data-member={member}>
          <dt>{member}</dt>
          <dd>{String(receipt[member])}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SignOffActionPanel({ gateId, slotId }: { gateId: string; slotId: string }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [readNonce, setReadNonce] = useState(0);
  const [result, setResult] = useState<SignOffResult | null>(null);
  const [inFlight, setInFlight] = useState(false);

  // The idempotency key, scoped to the exact six-member tuple it was minted for (Codex Q3). Held in a
  // ref, not state: it must never drive a render, and re-minting must never be a render side effect.
  const keyRef = useRef<{ identity: string; key: string } | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setLoad({ state: "loading" });
    readJson<ApprovalPreflight>(
      `/gw/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/approval-preflight`,
      ac.signal,
    )
      .then((model) => {
        // Discard a key minted for a DIFFERENT tuple: reusing it would change the server-side request
        // digest and earn a truthful `idempotency_key_mismatch`.
        const tuple = model.target_package_tuple;
        const identity = tuple ? tupleIdentity(tuple) : null;
        if (keyRef.current && keyRef.current.identity !== identity) keyRef.current = null;
        setLoad({ state: "ok", model });
      })
      .catch((e: unknown) => {
        if ((e as Error)?.name === "AbortError") return;
        const err = e as ReadError;
        setLoad({ state: "error", status: err?.status ?? 0, detail: err?.message ?? "read failed" });
      });
    return () => ac.abort();
  }, [gateId, slotId, readNonce]);

  const submit = useCallback(async () => {
    if (load.state !== "ok") return;
    const gate = attemptability(load.model, gateId, slotId);
    if (!gate.attemptable) return;            // defence in depth: the control is not rendered either
    const identity = tupleIdentity(gate.tuple);
    if (!keyRef.current || keyRef.current.identity !== identity) {
      // Minted LAZILY, on the first submit only — opening this page commits nothing. Random and
      // opaque: it carries no authority meaning and is not derived from the tuple or any principal.
      keyRef.current = { identity, key: crypto.randomUUID() };
    }
    setInFlight(true);
    let outcome: SignOffResult;
    try {
      const body = await postJson<SignOffReceipt>(
        signOffPath(gateId, slotId),
        signOffRequest(gate.tuple, keyRef.current.key),
      );
      outcome = classifySuccess(body);
    } catch (e: unknown) {
      outcome = classifyFailure(e as WriteError);
    }
    // Q3, strictly: the opaque value survives ONLY to serve an identical TRANSPORT retry. Every other
    // result — receipt, canonical outcome, seam refusal (503 included), contract drift — ends its
    // life here, so any later attempt mints a fresh one rather than silently reusing this request's.
    if (outcome.kind !== "transport") keyRef.current = null;
    setResult(outcome);
    setInFlight(false);
  }, [load, gateId, slotId]);

  if (load.state === "loading") {
    return (
      <section data-testid="sign-off-action" data-load="loading" aria-busy="true">
        <h1>Final-review sign-off</h1>
        <p>Loading the server-authored preflight…</p>
      </section>
    );
  }

  if (load.state === "error") {
    // A READ failure. No action is offered on top of evidence this surface could not obtain.
    return (
      <section data-testid="sign-off-action" data-load="error" data-status={load.status}>
        <h1>Final-review sign-off</h1>
        <p role="alert">Could not read the approval preflight: {load.detail}</p>
        <button type="button" data-testid="signoff-read-retry" onClick={() => setReadNonce((n) => n + 1)}>
          Retry read
        </button>
      </section>
    );
  }

  const model = load.model;
  const gate = attemptability(model, gateId, slotId);

  return (
    <section
      data-testid="sign-off-action"
      data-load="ok"
      data-attemptable={String(gate.attemptable)}
      data-attemptability={gate.reason}
      data-result={result?.kind ?? "none"}
    >
      <h1>Final-review sign-off</h1>

      <p data-testid="signoff-attemptability" data-reason={gate.reason}>
        {ATTEMPTABILITY_COPY[gate.reason]}
      </p>

      {/* The exact fields that would be forwarded, shown verbatim. Never edited or normalized. */}
      {gate.attemptable ? (
        <>
          <h2>Binding fields forwarded verbatim</h2>
          <dl data-testid="signoff-binding">
            <div data-member="snapshot_id">
              <dt>snapshot_id</dt>
              <dd>{gate.tuple.snapshot_id}</dd>
            </div>
            <div data-member="topic_revision">
              <dt>topic_revision</dt>
              <dd>{gate.tuple.topic_revision}</dd>
            </div>
            <div data-member="script_revision">
              <dt>script_revision</dt>
              <dd>{gate.tuple.script_revision}</dd>
            </div>
            <div data-member="workflow_version_id">
              <dt>workflow_version_id</dt>
              <dd>{gate.tuple.workflow_version_id}</dd>
            </div>
          </dl>
          <p>
            These are the server-authored pins for this target, sent unchanged. The gate and slot
            travel in the request path. No actor, principal, role, or authority field is sent.
          </p>
        </>
      ) : null}

      {/* The submit control exists ONLY for an attemptable target, and only before a result. */}
      {gate.attemptable && !result ? (
        <p>
          <button
            type="button"
            data-testid="signoff-submit"
            disabled={inFlight}
            onClick={() => void submit()}
          >
            {inFlight ? "Sending sign-off request…" : "Send sign-off request"}
          </button>
        </p>
      ) : null}

      {result ? (
        <div data-testid="signoff-result" data-kind={result.kind}>
          <h2>Result</h2>

          {result.kind === "receipt" ? (
            <>
              <p data-testid="signoff-outcome" data-code="recorded">
                The server recorded this sign-off and returned the receipt below. An identical retry
                returns this same receipt rather than recording a second one.
              </p>
              <Receipt receipt={result.receipt} />
            </>
          ) : null}

          {result.kind === "outcome" ? (
            // A server-authored canonical refusal, rendered verbatim and never reinterpreted.
            <>
              <p data-testid="signoff-outcome" data-code={result.code}>
                {OUTCOME_COPY[result.code]}
              </p>
              <Row label="Server result code" value={result.code} />
              <Row label="HTTP status" value={String(result.status)} />
            </>
          ) : null}

          {result.kind === "seam_refusal" ? (
            // NOT a sign-off decision: the workbench boundary declined before any upstream request.
            <>
              <p data-testid="signoff-seam-refusal" data-status={result.status}>
                {nonOutcomeCopy(result)}
              </p>
              <Row label="Boundary detail" value={result.detail} />
              <Row label="HTTP status" value={String(result.status)} />
            </>
          ) : null}

          {result.kind === "transport" ? (
            <p data-testid="signoff-transport">{nonOutcomeCopy(result)}</p>
          ) : null}

          {result.kind === "contract_drift" ? (
            // Codex Q2 — neutral, fail-closed, no retry, and the raw code always shown so the drift
            // cannot be masked. This is a presentation condition only; it is never sent anywhere.
            <>
              <p data-testid="signoff-contract-drift" data-status={result.status}>
                {nonOutcomeCopy(result)}
              </p>
              <Row label="Unrecognized server result" value={result.rawCode ?? "none supplied"} />
              <Row label="HTTP status" value={String(result.status)} />
              <Row label="Detail" value={result.detail} />
            </>
          ) : null}

          {/* Retry re-sends the IDENTICAL body with the SAME key, and is offered only where the
              outcome is genuinely unknown. A canonical refusal and contract drift never retry. */}
          {isRetryable(result) ? (
            <p>
              <button
                type="button"
                data-testid="signoff-retry"
                disabled={inFlight}
                onClick={() => {
                  setResult(null);
                  void submit();
                }}
              >
                Retry the identical request
              </button>
            </p>
          ) : null}

          {/* No optimistic transition: the authoritative state is re-read from the server, never
              patched locally. */}
          <p>
            <button
              type="button"
              data-testid="signoff-reread"
              onClick={() => {
                setResult(null);
                setReadNonce((n) => n + 1);
              }}
            >
              Re-read the server preflight
            </button>
          </p>
        </div>
      ) : null}

      <p>
        <Link
          data-testid="signoff-back-to-preflight"
          href={`/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/approval-preflight`}
        >
          Back to the approval-package preflight
        </Link>
      </p>
    </section>
  );
}
