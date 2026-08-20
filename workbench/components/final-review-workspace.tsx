"use client";

// R1 Stage 4 — the V2 Final Review workspace: the governed stage panel that makes the existing Stage-4
// surfaces REACHABLE from the run workspace and completes the vertical with the two canonical
// authority calls that were missing.
//
// WHAT WAS ACTUALLY MISSING. Every Stage-4 backend contract already existed — the immutable
// target-package (#423), the read projection (#427/#429), the approval-package preflight (#447/#448),
// the sign-off command and its strict receipt (#439/#440/#449). What did not exist was a path: the
// stage rail narrowed `final_review` away, the run workspace routed no panel for it, and the canonical
// `decide`/`resolve` authority was outside V2's write boundary. So evidence could be recorded and
// nothing could ever advance. This panel closes exactly that, and adds no new authority of its own.
//
// THE THREE FACTS STAY THREE FACTS, and the UI is laid out in the ONE ORDER THAT CAN SUCCEED:
//
//   INSPECT                  — the exact server-authored package + approval preflight.
//   AUTHORITY     decide     — the canonical governed decision through the gate.
//                              It records approval; it does not move the lifecycle.
//   EVIDENCE      sign-off   — immutable, attributable, exact-target-bound human receipt.
//                              It approves nothing and advances nothing.
//   TRANSITION    resolve    — the canonical lifecycle transition. The only thing that moves state.
//
// WHY DECIDE PRECEDES SIGN-OFF, AND WHY THAT IS NOT A NEW GATE. The backend contract already requires
// it: `engine.sign_off` revalidates present authority and refuses with `signoff_blocked` unless an
// authoritative APPROVED decision exists for the target. A surface that presented sign-off first
// implied evidence was independently actionable ahead of authority and described a sequence that could
// never complete. The order here is therefore a faithful rendering of the server's own precondition —
// this panel adds no precondition of its own, introduces no receipt gate, and still lets the SERVER
// alone decide whether sign-off may be attempted (the sign-off panel offers a control only while the
// server-authored preflight reports the target attemptable).
//
// Each step is a SEPARATE, EXPLICIT operator gesture. No gesture triggers another, none is chained,
// debounced, auto-submitted, or implied by the result of the one before it — ordering the steps is not
// sequencing them. Current advancement mode is MANUAL: that is this workflow's current governed
// behaviour, not a platform invariant, and nothing here would have to be redesigned for a future
// server-side policy to drive the same canonical `decide` + `resolve` path itself
// (see lib/final-review-advancement.ts).
//
// FAIL-CLOSED / NON-AUTHORITY INVARIANTS HELD HERE:
//   • the gate is the SERVER's (`stage_state.gate_id`) and the target list is the SERVER's
//     (`get_gate().targets`). This panel never searches for a gate, never picks among gates, and never
//     infers which slots are in final review from round membership or slot status;
//   • no lifecycle transition is EVER applied optimistically. After any accepted mutation the panel
//     re-reads the server and renders what came back — it does not advance a local state machine;
//   • a decision result is never used to conclude that the lifecycle moved, and a resolve result is
//     rendered as the server's own per-slot ledger, verbatim;
//   • no actor, principal, role, assignment, quorum, authority or eligibility value is composed,
//     displayed, or sent. The /gw route signs the principal server-side;
//   • the exact server-authored package tuple binds the decision's revision. Without a complete tuple
//     matching this exact target, the decision control is not offered at all.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApprovalPreflightPanel } from "./approval-preflight-panel";
import { SignOffActionPanel } from "./sign-off-action-panel";
import { FinalReviewProjectionPanel } from "./final-review-projection-panel";
import {
  postJson,
  readJson,
  ReadError,
  WriteError,
  type ApprovalPreflight,
  type ApprovalPreflightTuple,
  type FinalReviewStageState,
  type GateDetail,
  type GateTarget,
} from "@/lib/read-model";
import {
  ADVANCE_OFFER_COPY,
  advanceOffer,
  advancementNonAcceptedCopy,
  classifyAdvancementFailure,
  classifyDecideSuccess,
  classifyResolveSuccess,
  DECIDE_OFFER_COPY,
  decideOffer,
  decidePath,
  decideRequest,
  GATE_DECISIONS,
  resolvePath,
  resolveRequest,
  type AdvancementResult,
  type DecideAccepted,
  type GateDecision,
  type ResolveAccepted,
} from "@/lib/final-review-advancement";

type Load<T> =
  | { state: "loading" }
  | { state: "ok"; value: T }
  | { state: "error"; status: number; detail: string };

/** The URL key carrying the selected Final Review item, so a selection is link- and reload-stable —
 *  the same posture the shell takes for stage and lens. It carries canonical slot identity verbatim. */
const ITEM_KEY = "item";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <p>
      <strong>{label}:</strong> <span>{value}</span>
    </p>
  );
}

/** Render one advancement result. The server's own words, and an explicit statement of what this
 *  surface does NOT conclude from them. */
function ResultBlock<T>({
  testId,
  result,
  render,
}: {
  testId: string;
  result: AdvancementResult<T>;
  render: (value: T) => React.ReactNode;
}) {
  return (
    <div data-testid={testId} data-result-kind={result.kind} className="text-xs">
      {result.kind === "accepted" ? (
        render(result.value)
      ) : (
        <>
          <p data-testid={`${testId}-detail`}>
            {"status" in result ? `${result.status}: ` : ""}
            {result.detail}
          </p>
          <p className="text-(--color-muted)">{advancementNonAcceptedCopy(result.kind)}</p>
        </>
      )}
    </div>
  );
}

export function FinalReviewWorkspace({ roundId, gateStage }: { roundId: string; gateStage: string }) {
  const router = useRouter();
  const params = useSearchParams();

  // A single nonce re-reads BOTH server reads after any accepted mutation. It is the only mechanism by
  // which this panel's view of lifecycle state changes — there is deliberately no local mutation of
  // stage state, target outcome, or any lifecycle value anywhere in this component.
  const [readNonce, setReadNonce] = useState(0);
  const refetch = useCallback(() => setReadNonce((n) => n + 1), []);

  const [stage, setStage] = useState<Load<FinalReviewStageState>>({ state: "loading" });
  const [gate, setGate] = useState<Load<GateDetail> | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // THE TRANSITION RESULT LIVES AT GATE LEVEL, NOT ITEM LEVEL, and that is a correctness requirement
  // rather than a layout preference. A successful transition moves the slot to the stage's governed
  // `approve_to`, so the slot STOPS BEING A TARGET OF THIS GATE — the item legitimately disappears
  // from the server's own target list on the very next read. Holding the result inside the item meant
  // the operator clicked "apply", the item vanished, and the server's per-slot outcome ledger went
  // with it: the one moment the surface most needs to report what the authority did, it reported
  // nothing. Kept here, the ledger survives the target leaving the gate.
  const [transition, setTransition] = useState<
    { slotId: string; result: AdvancementResult<ResolveAccepted> } | null
  >(null);

  // AN INITIAL LOAD AND A REFRESH ARE DIFFERENT EVENTS, and collapsing them is not a cosmetic bug.
  // Resetting to `loading` on every re-read blanks out the gate id, which empties the target list,
  // which unmounts the selected item — destroying the server-authored result the operator was just
  // shown, by way of the refetch that result triggered. So a refresh KEEPS the last server-authored
  // value on screen until the next one arrives. That is not optimism: it is still the most recent
  // thing the server said, it is never a value this surface authored, and it is replaced the moment
  // the server answers again. A failed refresh surfaces the failure rather than the stale value.
  const stageIdentity = `${roundId}:${gateStage}`;
  const lastStageIdentity = useRef<string | null>(null);
  const lastGateIdentity = useRef<string | null>(null);

  // 1) The governed stage lifecycle state — the SERVER decides whether there is an active gate at all.
  useEffect(() => {
    const ac = new AbortController();
    if (lastStageIdentity.current !== stageIdentity) {
      lastStageIdentity.current = stageIdentity;
      setStage({ state: "loading" });
    }
    setRefreshing(true);
    readJson<FinalReviewStageState>(
      `/gw/rounds/${encodeURIComponent(roundId)}/stages/${encodeURIComponent(gateStage)}/state`,
      ac.signal,
    )
      .then((value) => setStage({ state: "ok", value }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setStage({
          state: "error",
          status: e instanceof ReadError ? e.status : 0,
          detail: e instanceof ReadError ? e.message : "the final review stage state could not be read",
        });
      })
      .finally(() => {
        if (!ac.signal.aborted) setRefreshing(false);
      });
    return () => ac.abort();
  }, [roundId, gateStage, stageIdentity, readNonce]);

  const gateId = stage.state === "ok" ? (stage.value.gate_id ?? null) : null;

  // 2) The canonical gate detail — the ONLY truthful source of which slots this gate governs and what
  //    the server has recorded for each. Read only when the server reported a gate.
  useEffect(() => {
    if (!gateId) {
      setGate(null);
      lastGateIdentity.current = null;
      return;
    }
    const ac = new AbortController();
    if (lastGateIdentity.current !== gateId) {
      lastGateIdentity.current = gateId;
      setGate({ state: "loading" });
    }
    readJson<GateDetail>(`/gw/gates/${encodeURIComponent(gateId)}`, ac.signal)
      .then((value) => setGate({ state: "ok", value }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setGate({
          state: "error",
          status: e instanceof ReadError ? e.status : 0,
          detail: e instanceof ReadError ? e.message : "the canonical gate could not be read",
        });
      });
    return () => ac.abort();
  }, [gateId, readNonce]);

  const targets: readonly GateTarget[] =
    gate?.state === "ok" && Array.isArray(gate.value.targets) ? gate.value.targets : [];
  const targetIds = targets.map((t) => t.slot_id);

  // Selection resolves against the SERVER's target list, fail-closed: an unknown or stale `?item=`
  // never selects something the gate does not govern — it falls back to the first canonical target,
  // exactly as the shell canonicalizes an unknown stage rather than rendering a stale surface.
  const rawItem = params?.get(ITEM_KEY) ?? null;
  const selectedId = rawItem && targetIds.includes(rawItem) ? rawItem : (targetIds[0] ?? null);
  const selected = targets.find((t) => t.slot_id === selectedId) ?? null;

  const selectItem = useCallback(
    (slotId: string) => {
      const next = new URLSearchParams(params?.toString() ?? "");
      next.set(ITEM_KEY, slotId);
      router.replace(`?${next.toString()}`, { scroll: false });
    },
    [params, router],
  );

  return (
    <div
      data-testid="final-review-workspace"
      data-round-id={roundId}
      data-gate-stage={gateStage}
      data-gate-id={gateId ?? ""}
      data-stage-load={stage.state}
      data-refreshing={refreshing ? "true" : "false"}
      data-lifecycle-state={stage.state === "ok" ? (stage.value.state ?? "") : ""}
      className="flex flex-col gap-3"
    >
      <StageHeader stage={stage} />

      {stage.state === "ok" && !gateId && (
        // A truthful, non-error state: the server reports no active final-review gate. Never rendered
        // as an empty item list, which would read as "this run has nothing to review".
        <p data-testid="final-review-no-gate" className="text-xs text-(--color-muted)">
          The server reports no active final-review gate for this run at present. No final-review item
          is offered, and nothing is inferred about why — the stage state above is the server&apos;s own.
        </p>
      )}

      {gate?.state === "loading" && <p className="text-xs">Reading the canonical gate…</p>}
      {gate?.state === "error" && (
        <p data-testid="final-review-gate-error" className="text-xs">
          The canonical gate could not be read ({gate.status}): {gate.detail}. No target list is shown,
          and none is reconstructed from round membership or slot status.
        </p>
      )}

      {gate?.state === "ok" && targets.length === 0 && (
        <p data-testid="final-review-no-targets" className="text-xs text-(--color-muted)">
          The canonical gate governs no targets at present.
        </p>
      )}

      {targets.length > 0 && (
        <TargetList targets={targets} selectedId={selectedId} onSelect={selectItem} />
      )}

      {transition && (
        <section data-testid="final-review-transition-record" data-slot-id={transition.slotId} className="text-xs">
          <h3 className="text-sm font-semibold">Last canonical transition</h3>
          <p className="text-[11px] text-(--color-muted)">
            For <span className="font-mono">{transition.slotId}</span>. An advanced target leaves this
            gate, so it may no longer appear in the list above — the state above is re-read from the
            server either way.
          </p>
          <ResultBlock
            testId="final-review-resolve-result"
            result={transition.result}
            render={(v) => {
              const entries = Object.entries(v.outcomes);
              return (
                <div data-testid="final-review-resolve-outcomes" data-outcome-count={entries.length}>
                  {entries.length === 0 ? (
                    <p>The canonical transition returned an empty outcome ledger: the server moved nothing.</p>
                  ) : (
                    <ul className="list-disc pl-4">
                      {entries.map(([sid, out]) => (
                        <li key={sid} data-testid="final-review-resolve-outcome" data-slot-id={sid} data-outcome={out}>
                          <span className="font-mono">{sid}</span>: {out}
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="text-(--color-muted)">
                    This is the server&apos;s own per-slot ledger, rendered verbatim. The authoritative
                    state above is re-read from the server rather than derived from it.
                  </p>
                </div>
              );
            }}
          />
        </section>
      )}

      {gateId && selected && selectedId && (
        // The key deliberately EXCLUDES `readNonce`. Keying on it would remount this subtree on every
        // refetch — including the refetch an accepted decision itself triggers — silently destroying
        // the server-authored result the operator just received. Re-reading server truth and erasing
        // the record of what the server said are different things, and only the first is wanted. The
        // nonce is passed as a PROP instead, so the read-only panels below re-read while the action
        // results persist.
        <FinalReviewItem
          key={`${gateId}:${selectedId}`}
          gateId={gateId}
          slotId={selectedId}
          targetIds={targetIds}
          outcome={selected.current_outcome ?? null}
          readNonce={readNonce}
          onServerStateChanged={refetch}
          onTransitionResult={(slotId, result) => setTransition({ slotId, result })}
        />
      )}
    </div>
  );
}

function StageHeader({ stage }: { stage: Load<FinalReviewStageState> }) {
  if (stage.state === "loading") return <p className="text-xs">Reading the final review stage state…</p>;
  if (stage.state === "error") {
    return (
      <p data-testid="final-review-stage-error" className="text-xs">
        The final review stage state could not be read ({stage.status}): {stage.detail}. Nothing is
        assumed about the stage in its absence.
      </p>
    );
  }
  const s = stage.value;
  return (
    <section data-testid="final-review-stage" className="flex flex-col gap-1 text-xs">
      <h2 className="text-sm font-semibold">Final Review</h2>
      {/* Server-authored lifecycle truth, rendered verbatim. */}
      <Row label="Lifecycle state" value={String(s.state ?? "unknown")} />
      <Row label="Canonical gate" value={s.gate_id ? String(s.gate_id) : "none reported"} />
      <p data-testid="final-review-counts">
        in review {s.in_review ?? 0} · approved {s.approved ?? 0} · sent back {s.sent_back ?? 0} ·
        rejected {s.rejected ?? 0} · pending {s.pending ?? 0} · advanced {s.advanced ?? 0}
      </p>
      {s.recommendation && (
        // Advisory only. Rendered as the server's words and labelled as advice, never as an
        // instruction this surface endorses or acts on.
        <p data-testid="final-review-recommendation" className="text-(--color-muted)">
          Server advisory: {s.recommendation}
        </p>
      )}
      {Array.isArray(s.warnings) && s.warnings.length > 0 && (
        <ul data-testid="final-review-warnings" className="list-disc pl-4">
          {s.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TargetList({
  targets,
  selectedId,
  onSelect,
}: {
  targets: readonly GateTarget[];
  selectedId: string | null;
  onSelect: (slotId: string) => void;
}) {
  return (
    <section data-testid="final-review-targets" aria-label="Final review items" className="flex flex-col gap-1">
      <ul className="flex flex-wrap gap-2">
        {targets.map((t) => {
          const isSelected = t.slot_id === selectedId;
          return (
            <li key={t.slot_id}>
              <button
                type="button"
                data-testid="final-review-target"
                data-slot-id={t.slot_id}
                // The SERVER's rollup, surfaced as a selector-stable attribute and as text. Never
                // recomputed here from decisions, and never inferred from slot status.
                data-current-outcome={t.current_outcome ?? "unknown"}
                data-selected={isSelected ? "true" : "false"}
                aria-current={isSelected ? "true" : undefined}
                onClick={() => onSelect(t.slot_id)}
                className="rounded border px-2 py-1 text-xs"
              >
                <span className="font-mono">{t.slot_id}</span>
                <span className="ml-2 text-(--color-muted)">{t.current_outcome ?? "unknown"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/**
 * One Final Review item: inspection, evidence, authority, transition — in that order, as four
 * visually and functionally separate blocks.
 *
 * The ORDER is the semantics. Inspect the exact server-authored package, then record human evidence,
 * then take the governed decision, then explicitly apply the transition. Nothing in the chain runs
 * itself, and the panel says so at each step rather than leaving the operator to assume.
 */
function FinalReviewItem({
  gateId,
  slotId,
  targetIds,
  outcome,
  readNonce,
  onServerStateChanged,
  onTransitionResult,
}: {
  gateId: string;
  slotId: string;
  targetIds: readonly string[];
  outcome: string | null;
  /** Bumped after any accepted mutation. Drives a re-read of every server-authored value on this
   *  item — the pinned tuple and the three read-only panels — without disturbing action results. */
  readNonce: number;
  onServerStateChanged: () => void;
  /** Reports the canonical transition result UP to the gate level, where it survives this item
   *  leaving the gate's target list (which is exactly what a successful transition causes). */
  onTransitionResult: (slotId: string, result: AdvancementResult<ResolveAccepted>) => void;
}) {
  // The exact server-authored package tuple. Read here SOLELY to bind the decision to the exact
  // reviewed revision — the full preflight verdict is rendered by the panel below, which reads it
  // itself. Neither derives the tuple; both consume the same server-authored one.
  const [tuple, setTuple] = useState<Load<ApprovalPreflightTuple | null>>({ state: "loading" });

  useEffect(() => {
    const ac = new AbortController();
    setTuple({ state: "loading" });
    readJson<ApprovalPreflight>(
      `/gw/gates/${encodeURIComponent(gateId)}/slots/${encodeURIComponent(slotId)}/approval-preflight`,
      ac.signal,
    )
      .then((m) => setTuple({ state: "ok", value: m.target_package_tuple ?? null }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setTuple({
          state: "error",
          status: e instanceof ReadError ? e.status : 0,
          detail: e instanceof ReadError ? e.message : "the approval preflight could not be read",
        });
      });
    return () => ac.abort();
  }, [gateId, slotId, readNonce]);

  const resolvedTuple = tuple.state === "ok" ? tuple.value : null;
  const dOffer = decideOffer(gateId, slotId, targetIds, resolvedTuple);
  const aOffer = advanceOffer(gateId, slotId, targetIds, outcome);

  return (
    <section
      data-testid="final-review-item"
      data-gate-id={gateId}
      data-slot-id={slotId}
      data-current-outcome={outcome ?? "unknown"}
      className="flex flex-col gap-4 border-t pt-3"
    >
      {/* ---- 1. INSPECT: the exact server-authored package + approval preflight ----
           Keyed on the nonce so it RE-READS after any accepted mutation. These are pure read-only
           projections with no operator input to lose, and showing a pre-transition eligibility
           verdict beside a post-transition lifecycle state would be the surface contradicting
           itself. Re-reading it after the decision is also what surfaces the server flipping this
           target from `signoff_blocked` to attemptable. The sign-off panel is deliberately NOT keyed
           this way: it holds a receipt the operator just created, and discarding that on an unrelated
           decision would read as the evidence having been undone. It re-reads on its own retry. */}
      <div data-testid="final-review-inspect">
        <ApprovalPreflightPanel key={`preflight:${readNonce}`} gateId={gateId} slotId={slotId} />
      </div>

      {/* ---- 2. AUTHORITY: the canonical governed gate decision ----
           ORDERED BEFORE EVIDENCE BECAUSE THE BACKEND CONTRACT ORDERS IT THAT WAY. `engine.sign_off`
           revalidates present authority and refuses with `signoff_blocked` until an authoritative
           APPROVED gate decision exists for the target — observed live as "the present decision
           outcome is 'pending', which is not an actionable approved state". An earlier revision of
           this panel presented sign-off first, which made evidence look independently actionable
           ahead of authority and contradicted the only sequence that can actually succeed.
           Reordering changes no authority and adds no gate: the server enforced this all along and
           still does. It only stops the surface from teaching the operator the wrong order. */}
      <DecisionBlock
        gateId={gateId}
        offer={dOffer}
        tupleLoad={tuple}
        onServerStateChanged={onServerStateChanged}
      />

      {/* ---- 3. EVIDENCE: the immutable human sign-off. Advances nothing. ----
           Still evidence-only, and still gated by the SERVER alone: the panel offers a submit control
           only while the server-authored preflight reports the target attemptable, so it stays
           withheld before an approved outcome exists and no client-side precondition is added here.

           KEYED ON THE SERVER-AUTHORED OUTCOME, not on the refetch nonce, because the two goals here
           genuinely conflict and the outcome is what separates them. A recorded DECISION changes the
           outcome, which is exactly the event that flips the server's preflight from `signoff_blocked`
           to attemptable — so the panel must re-read then, or the control would never appear without a
           manual reload. A SIGN-OFF does not change the outcome (that is the whole point of evidence),
           so the key is stable across it and the receipt the operator just created survives. Neither
           behaviour is a client-side precondition: the key only decides when to ASK the server again. */}
      <div data-testid="final-review-evidence" className="flex flex-col gap-1">
        <p className="text-[11px] text-(--color-muted)">
          Sign-off records immutable human evidence bound to this exact package. It is not an approval,
          it grants no authority, and it does not advance the lifecycle. The canonical command
          revalidates present authority when it runs and refuses while the governed decision above has
          not produced an approved outcome — so this step follows the decision rather than replacing
          it, and the transition below remains a separate, explicit operation.
        </p>
        <SignOffActionPanel key={`signoff:${outcome ?? "unknown"}`} gateId={gateId} slotId={slotId} />
      </div>

      {/* ---- 4. TRANSITION: the canonical lifecycle advance, explicitly invoked ---- */}
      <AdvanceBlock
        gateId={gateId}
        slotId={slotId}
        offer={aOffer}
        onServerStateChanged={onServerStateChanged}
        onResult={onTransitionResult}
      />

      {/* ---- Immutable sign-off / decision evidence as the server projects it ---- */}
      <div data-testid="final-review-projection">
        <FinalReviewProjectionPanel key={`projection:${readNonce}`} gateId={gateId} slotId={slotId} />
      </div>
    </section>
  );
}

function DecisionBlock({
  gateId,
  offer,
  tupleLoad,
  onServerStateChanged,
}: {
  gateId: string;
  offer: ReturnType<typeof decideOffer>;
  tupleLoad: Load<ApprovalPreflightTuple | null>;
  onServerStateChanged: () => void;
}) {
  const [decision, setDecision] = useState<GateDecision>("approve");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AdvancementResult<DecideAccepted> | null>(null);

  const submit = useCallback(async () => {
    if (!offer.offered || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const body = await postJson<unknown>(decidePath(gateId), decideRequest(decision, offer.tuple, notes));
      const classified = classifyDecideSuccess(body);
      setResult(classified);
      // Re-read the server ONLY. A recorded decision changes the gate's target outcome, and this panel
      // learns that from the server's next answer — never from a local assumption about what a
      // decision implies. Nothing advances here: the transition is a separate gesture.
      if (classified.kind === "accepted") onServerStateChanged();
    } catch (e: unknown) {
      setResult(
        e instanceof WriteError
          ? classifyAdvancementFailure<DecideAccepted>(e)
          : { kind: "transport", detail: "the decision request did not complete" },
      );
    } finally {
      setBusy(false);
    }
  }, [offer, busy, gateId, decision, notes, onServerStateChanged]);

  return (
    <div
      data-testid="final-review-decision"
      data-offered={offer.offered ? "true" : "false"}
      data-offer-reason={offer.reason}
      className="flex flex-col gap-1 text-xs"
    >
      <h3 className="text-sm font-semibold">Governed decision</h3>
      <p className="text-[11px] text-(--color-muted)">{DECIDE_OFFER_COPY[offer.reason]}</p>

      {tupleLoad.state === "error" && (
        <p data-testid="final-review-tuple-error">
          The approval preflight could not be read ({tupleLoad.status}): {tupleLoad.detail}. No decision
          is offered without the server-authored package binding.
        </p>
      )}

      {offer.offered && (
        <>
          {/* The exact revision the decision will be bound to — the server's own pin, shown so the
              operator can see what is being approved, not a value this surface computed. */}
          <p data-testid="final-review-decision-binding">
            Binds to server-authored script revision{" "}
            <span data-testid="final-review-decision-revision">{offer.tuple.script_revision}</span> of{" "}
            <span className="font-mono">{offer.tuple.slot_id}</span>.
          </p>
          <label className="flex items-center gap-2">
            <span>Decision</span>
            <select
              data-testid="final-review-decision-select"
              value={decision}
              onChange={(e) => setDecision(e.target.value as GateDecision)}
              className="rounded border px-1 py-0.5"
            >
              {GATE_DECISIONS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          {decision === "request_change" && (
            <label className="flex flex-col gap-1">
              {/* The canonical command REQUIRES this rationale. The field mirrors that requirement; the
                  server still enforces it and this surface relays the refusal rather than pre-judging. */}
              <span>Rationale (the canonical command requires one for request_change)</span>
              <textarea
                data-testid="final-review-decision-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={2}
                className="rounded border px-1 py-0.5"
              />
            </label>
          )}
          <button
            type="button"
            data-testid="final-review-decide"
            disabled={busy}
            onClick={submit}
            className="self-start rounded border px-2 py-1"
          >
            {busy ? "Recording the decision…" : "Record the governed decision"}
          </button>
          <p className="text-[11px] text-(--color-muted)">
            This records the decision through the canonical gate authority. It does not advance the
            lifecycle — applying it is the separate transition below.
          </p>
        </>
      )}

      {result && (
        <ResultBlock
          testId="final-review-decide-result"
          result={result}
          render={(v) => (
            // The server's own list of targets it recorded the decision over, rendered verbatim.
            <p data-testid="final-review-decide-touched" data-touched-count={v.touched.length}>
              The canonical gate recorded the decision over {v.touched.length} target(s)
              {v.touched.length ? `: ${v.touched.join(", ")}` : ""}. This is a recorded decision only;
              no lifecycle transition has been applied by it.
            </p>
          )}
        />
      )}
    </div>
  );
}

function AdvanceBlock({
  gateId,
  slotId,
  offer,
  onServerStateChanged,
  onResult,
}: {
  gateId: string;
  slotId: string;
  offer: ReturnType<typeof advanceOffer>;
  onServerStateChanged: () => void;
  onResult: (slotId: string, result: AdvancementResult<ResolveAccepted>) => void;
}) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(async () => {
    if (!offer.offered || busy) return;
    setBusy(true);
    try {
      const body = await postJson<unknown>(resolvePath(gateId), resolveRequest(slotId));
      const classified = classifyResolveSuccess(body);
      onResult(slotId, classified);
      // Re-read the server. The authoritative lifecycle state is whatever the server now reports —
      // this panel never writes a transition into its own state, so a refused or partial resolve can
      // never look like a successful advance.
      if (classified.kind === "accepted") onServerStateChanged();
    } catch (e: unknown) {
      onResult(
        slotId,
        e instanceof WriteError
          ? classifyAdvancementFailure<ResolveAccepted>(e)
          : { kind: "transport", detail: "the transition request did not complete" },
      );
    } finally {
      setBusy(false);
    }
  }, [offer, busy, gateId, slotId, onServerStateChanged, onResult]);

  return (
    <div
      data-testid="final-review-advance"
      data-offered={offer.offered ? "true" : "false"}
      data-offer-reason={offer.reason}
      className="flex flex-col gap-1 text-xs"
    >
      <h3 className="text-sm font-semibold">Lifecycle transition</h3>
      <p className="text-[11px] text-(--color-muted)">{ADVANCE_OFFER_COPY[offer.reason]}</p>

      {offer.offered && (
        <>
          <button
            type="button"
            data-testid="final-review-resolve"
            disabled={busy}
            onClick={submit}
            className="self-start rounded border px-2 py-1"
          >
            {busy ? "Applying the canonical transition…" : "Apply the canonical transition"}
          </button>
          <p className="text-[11px] text-(--color-muted)">
            The server applies the governed quorum and decides what actually moves. This surface does
            not predict the outcome and shows no state until the server has answered.
          </p>
        </>
      )}

    </div>
  );
}
