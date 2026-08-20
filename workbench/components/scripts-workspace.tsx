"use client";

// #355 — the Scripts stage lens. READ-FIRST BY PROOF, not by preference.
//
// WHY THERE IS NO "GENERATE" BUTTON HERE. `script_review` is a fully canonical stage: it has an AI
// generator, a `TOPIC_APPROVED` input contract, a `scripts` writer mode, and `POST /rounds/{id}/
// stages/script_review/generate` already accepts it (gates/api.py:698-760). What it does NOT have is
// authorization: the `_require_trusted_principal` + authorize + audit block in that route lives
// entirely inside `if mode == "topics":` (#332). For `scripts` the request falls through to the job
// starter with no authentication, no authorization and no audit trail.
//
// V1 reaches that route behind its own authenticated proxy, so this is not a defect claim against
// the backend. But V2's seam is unauthenticated by design (#293) — putting the call on V2's write
// allowlist would let any caller who can reach the workbench start a writer job with no principal at
// all. That would be a NEW authority gap created by this slice, strictly worse than the one that
// kept Topic *retry* unexposed. So the stage ships read-only and says exactly why, rather than
// showing a control that would either lie or be dangerous.
//
// Everything rendered below is canonical server state. Nothing is derived, defaulted or invented; an
// absent read is an explicit unavailable state, never an empty success.

import { useCallback, useEffect, useRef, useState } from "react";
import { readJson, ReadError, postJson, WriteError,
  type ScriptActionDecision, type ScriptRevision, type StageState,
  type TopicItemReadModel } from "@/lib/read-model";

type Load<T> = { phase: "loading" } | { phase: "ok"; data: T } | { phase: "error"; detail: string; status: number };

function useRead<T>(path: string): Load<T> {
  const [state, setState] = useState<Load<T>>({ phase: "loading" });
  useEffect(() => {
    const ac = new AbortController();
    setState({ phase: "loading" });
    readJson<T>(path, ac.signal)
      .then((data) => setState({ phase: "ok", data }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        const err = e instanceof ReadError ? e : null;
        setState({ phase: "error", detail: err?.message ?? "read failed", status: err?.status ?? 0 });
      });
    return () => ac.abort();
  }, [path]);
  return state;
}

/** #357 — the governed generation control, PROJECTED from the server's typed action decision.
 *
 *  #355 shipped this as a hardcoded unavailable state, for a proven reason: the canonical route had no
 *  principal authorization on this seam, so offering the control would have exposed an unauthenticated
 *  write. #357 closed that gap, so the control is offered — but ONLY as the server describes it. V2
 *  never decides availability, never infers a reason, and never invents a denial: every state below is
 *  a projection of `reason_code`, so the surface cannot disagree with the authority that governs it. */
function GenerationControl({ roundId, gateStage }: { roundId: string; gateStage: string }) {
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const path = `/gw/rounds/${encodeURIComponent(roundId)}/stages/${encodeURIComponent(gateStage)}/action`;
  const [decision, setDecision] = useState<Load<ScriptActionDecision>>({ phase: "loading" });

  useEffect(() => {
    const ac = new AbortController();
    setDecision({ phase: "loading" });
    readJson<ScriptActionDecision>(path, ac.signal)
      .then((d) => setDecision({ phase: "ok", data: d }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        const err = e instanceof ReadError ? e : null;
        setDecision({ phase: "error", detail: err?.message ?? "read failed", status: err?.status ?? 0 });
      });
    return () => ac.abort();
  }, [path, nonce]);

  const start = useCallback(async () => {
    setBusy(true); setRefusal(null);
    try {
      await postJson(`/gw/rounds/${encodeURIComponent(roundId)}/stages/${encodeURIComponent(gateStage)}/generate`, {});
    } catch (e: unknown) {
      // The server's typed refusal is relayed verbatim — never restated as a friendlier guess.
      setRefusal(e instanceof WriteError ? e.message : "the request was refused");
    } finally {
      setBusy(false); setNonce((n) => n + 1);
    }
  }, [roundId, gateStage]);

  if (decision.phase === "loading") {
    return <section data-testid="scripts-generation" className="rounded-md border border-(--color-border) p-3 text-xs">
      <p data-testid="scripts-generation-loading" className="text-(--color-muted)">Checking generation state…</p>
    </section>;
  }
  if (decision.phase === "error") {
    return <section data-testid="scripts-generation" className="rounded-md border border-(--color-border) p-3 text-xs">
      <p data-testid="scripts-generation-error" className="text-(--color-muted)">
        Generation state unavailable — the server reported: {decision.detail}
      </p>
    </section>;
  }
  const d = decision.data;
  return (
    <section data-testid="scripts-generation" data-reason-code={d.reason_code ?? ""}
             data-available={d.available ? "true" : "false"}
             className="rounded-md border border-(--color-border) p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">Script generation</span>
        <span data-testid="scripts-generation-state"
              className="rounded-full border border-(--color-border) px-2 py-0.5 text-[11px]">
          {d.available ? "Available" : (d.reason_code ?? "unavailable")}
        </span>
        {d.available && (
          <button type="button" data-testid="scripts-generate" disabled={busy} onClick={start}
                  className="rounded-md border border-(--color-fg) px-2.5 py-1 text-xs font-semibold">
            {busy ? "Starting…" : "Generate scripts"}
          </button>
        )}
      </div>
      {d.detail && <p data-testid="scripts-generation-detail" className="mt-1 text-(--color-muted)">{d.detail}</p>}
      {refusal && <p data-testid="scripts-generation-refusal" className="mt-1 text-(--color-muted)">{refusal}</p>}
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-[11px] text-(--color-muted)">
        {d.attempt_id && (<><dt>attempt</dt><dd data-testid="scripts-attempt-id" className="font-mono">{d.attempt_id}</dd></>)}
        {d.job_status && (<><dt>job</dt><dd data-testid="scripts-job-status" className="font-mono">{d.job_status}</dd></>)}
        {d.manifest_digest && (<><dt>manifest</dt><dd data-testid="scripts-manifest-digest" className="font-mono">{d.manifest_digest.slice(0, 16)}</dd></>)}
        {typeof d.input_revisions?.length === "number" && (
          <><dt>pinned inputs</dt><dd data-testid="scripts-pinned-count">{d.input_revisions.length}</dd></>)}
      </dl>
    </section>
  );
}

function StageStatePanel({ roundId, gateStage }: { roundId: string; gateStage: string }) {
  // Addressed by the GOVERNED gate, not by a hard-coded literal: the workflow version decides which
  // gate this stage belongs to. If a version maps it to a gate outside V2's enumerated boundary the
  // read is refused (403) and rendered as unavailable — fail closed, never a wrong-gate read.
  const state = useRead<StageState>(
    `/gw/rounds/${encodeURIComponent(roundId)}/stages/${encodeURIComponent(gateStage)}/state`);
  return (
    <section data-testid="scripts-stage-state" className="rounded-md border border-(--color-border) p-3 text-xs">
      <h3 className="font-semibold">Stage state</h3>
      {state.phase === "loading" && <p data-testid="scripts-state-loading" className="text-(--color-muted)">Loading…</p>}
      {state.phase === "error" && (
        <p data-testid="scripts-state-error" className="text-(--color-muted)">
          Unavailable — the server reported: {state.detail}
        </p>
      )}
      {state.phase === "ok" && (
        <dl data-testid="scripts-state-ok" className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
          {Object.entries(state.data)
            .filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v))
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-(--color-muted)">{k}</dt>
                <dd className="font-mono">{v === null ? "—" : String(v)}</dd>
              </div>
            ))}
        </dl>
      )}
    </section>
  );
}

/** #367 — the governed Script review LIFECYCLE controls, PROJECTED from the server's typed per-item
 *  action map (`topic_item?artifact=script`). Every control is offered ONLY as the server's `actions`
 *  map allows it; a denied action shows the machine reason verbatim; a refused write relays the typed
 *  WriteError. V2 decides no availability, infers no state, and mints no authority — the surface cannot
 *  disagree with the guard that governs the mutation. All writes carry `artifact:"script"`, and the
 *  ones the server requires a durable identity for (rework, edit, restore) carry a canonical
 *  idempotency key so a double-submit converges on one revision rather than racing. */
function SlotLifecycle({ slotId }: { slotId: string }) {
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  // Explicit reviewer inputs — no action submits a placeholder or blanks a field.
  const [editValue, setEditValue] = useState("");
  const [rcComment, setRcComment] = useState("");
  const [reworkComment, setReworkComment] = useState("");
  // A canonical idempotency key is PERSISTED per pending payload, so a retry after an ambiguous
  // failure sends the SAME key and the server converges on one operation rather than appending a
  // second revision. The key rotates only when the payload materially changes or after a known
  // success (cleared in the click handlers). One ref per durable-identity action (edit, rework).
  const editKey = useRef<{ sig: string; key: string } | null>(null);
  const reworkKey = useRef<{ sig: string; key: string } | null>(null);
  // #373 (focus restoration, scoped per preflight) — after a governed action settles, the acted control
  // can UNMOUNT (the action set changes on re-read), which would strand keyboard/AT focus on <body>.
  // Move focus to the announced status region (role=status aria-live) so recovery is predictable on
  // success AND refusal. Reuses the existing in-repo statusRef pattern; no global/shell change.
  const [notice, setNotice] = useState<string | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if ((notice || refusal) && !busy) statusRef.current?.focus();
  }, [notice, refusal, busy]);
  const mint = useCallback(
    () => (globalThis.crypto?.randomUUID?.() ?? `${slotId}-${Date.now()}-${Math.round(Math.random() * 1e9)}`),
    [slotId]);
  const keyFor = useCallback((ref: typeof editKey, sig: string) => {
    if (ref.current && ref.current.sig === sig) return ref.current.key;   // same payload -> same key
    const key = mint();
    ref.current = { sig, key };                                            // changed payload -> new identity
    return key;
  }, [mint]);
  const path = `/gw/slots/${encodeURIComponent(slotId)}/topic_item?artifact=script`;
  const [item, setItem] = useState<Load<TopicItemReadModel>>({ phase: "loading" });

  useEffect(() => {
    const ac = new AbortController();
    setItem({ phase: "loading" });
    readJson<TopicItemReadModel>(path, ac.signal)
      .then((d) => setItem({ phase: "ok", data: d }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        const err = e instanceof ReadError ? e : null;
        setItem({ phase: "error", detail: err?.message ?? "read failed", status: err?.status ?? 0 });
      });
    return () => ac.abort();
  }, [path, nonce]);

  const post = useCallback(async (key: string, seg: string, body: Record<string, unknown>): Promise<boolean> => {
    setBusy(key); setRefusal(null); setNotice(null);
    try {
      await postJson(`/gw/slots/${encodeURIComponent(slotId)}/${seg}`, { artifact: "script", ...body });
      setNotice(`${seg} recorded`);
      return true;
    } catch (e: unknown) {
      // Relay the SERVER's typed refusal verbatim — the coded error AND its machine reason (e.g.
      // "governed_denial: approved_or_downstream"), never a friendlier restatement or a bare failure.
      if (e instanceof WriteError) {
        setRefusal([e.error, e.reason].filter(Boolean).join(": ") || e.message);
      } else {
        setRefusal("the request was refused");
      }
      return false;
    } finally {
      setBusy(null); setNonce((n) => n + 1);
    }
  }, [slotId]);

  // #373 (Codex ruling 2) — gate-scoped pre-commit undo. undecide is POST /gates/{gate_id}/undecide;
  // the gate id is the server-projected authoritative_gate_id, consumed directly. A typed refusal
  // (already submitted / no decision) is relayed verbatim and is non-mutating.
  const postUndecide = useCallback(async (gateId: string): Promise<boolean> => {
    setBusy("undecide"); setRefusal(null); setNotice(null);
    try {
      await postJson(`/gw/gates/${encodeURIComponent(gateId)}/undecide`, { slot_ids: [slotId] });
      setNotice("decision cleared");
      return true;
    } catch (e: unknown) {
      if (e instanceof WriteError) {
        setRefusal([e.error, e.reason].filter(Boolean).join(": ") || e.message);
      } else {
        setRefusal("the request was refused");
      }
      return false;
    } finally {
      setBusy(null); setNonce((n) => n + 1);
    }
  }, [slotId]);

  if (item.phase === "loading") {
    return <p data-testid={`scripts-actions-loading-${slotId}`} className="text-[11px] text-(--color-muted)">Reading item state…</p>;
  }
  if (item.phase === "error") {
    // An absent read is an explicit unavailable state — never an empty success or an assumed action set.
    return <p data-testid={`scripts-actions-error-${slotId}`} className="text-[11px] text-(--color-muted)">
      Item actions unavailable — the server reported: {item.detail}
    </p>;
  }
  const it = item.data;
  const head = it.head_revision;
  const a = it.actions ?? {};

  const denied = (name: string) => {
    const act = a[name];
    if (!act || act.allowed) return null;
    return <span data-testid={`scripts-action-${name}-denied-${slotId}`}
      className="text-[11px] text-(--color-muted)">{name}: unavailable ({act.reason ?? "denied"})</span>;
  };
  const allowed = (name: string) => Boolean(a[name]?.allowed);

  return (
    <div data-testid={`scripts-actions-${slotId}`} data-head={head}
         data-approved={it.approved_revision ?? ""} className="mt-1 flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1">
        {/* Approve pins the EXACT head the surface is showing (CAS on expected_revision). */}
        {allowed("approve") ? (
          <button type="button" disabled={busy !== null} data-testid={`scripts-action-approve-${slotId}`}
            onClick={() => post("approve", "approve", { expected_revision: head })}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "approve" ? "Approving…" : `Approve rev ${head}`}
          </button>
        ) : denied("approve")}
        {/* Drop / restore carry no reviewer text; a fresh idempotency key is minted at SUBMIT. */}
        {allowed("drop") ? (
          <button type="button" disabled={busy !== null} data-testid={`scripts-action-drop-${slotId}`}
            onClick={() => post("drop", "drop", {})}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "drop" ? "Dropping…" : "Drop"}
          </button>
        ) : denied("drop")}
        {/* #373 (Codex ruling 1) — canonical `reopen` (reverse a committed decision) labelled 1:1 to
            the reopen endpoint. This REPLACES the prior "Restore"→reopen alias, which gated a reopen
            call on `restore`(=restore_revision) eligibility; the label + action key now match the
            command exactly. */}
        {allowed("reopen") ? (
          <button type="button" disabled={busy !== null} data-testid={`scripts-action-reopen-${slotId}`}
            onClick={() => post("reopen", "reopen", {})}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "reopen" ? "Reopening…" : "Reopen"}
          </button>
        ) : denied("reopen")}
        {/* #373 (Codex ruling 2) — pre-commit UNDO, addressed to the server-projected authoritative gate
            id (consumed directly; never a client gate choice). Typed-unavailable when not exactly one
            applicable gate / no decision. */}
        {allowed("undecide") && it.authoritative_gate_id ? (
          <button type="button" disabled={busy !== null} data-testid={`scripts-action-undecide-${slotId}`}
            data-gate={it.authoritative_gate_id}
            onClick={() => postUndecide(it.authoritative_gate_id as string)}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "undecide" ? "Clearing…" : "Undo decision"}
          </button>
        ) : denied("undecide")}
      </div>

      {/* EDIT — an explicit new value for the whitelisted final_line field. An empty value is refused
          client-side (blanking is not an edit), and the idempotency key is minted at submit. */}
      {allowed("edit") ? (
        <div className="flex flex-wrap items-center gap-1">
          <input data-testid={`scripts-edit-value-${slotId}`} value={editValue}
            onChange={(e) => setEditValue(e.target.value)} placeholder="new final line"
            className="rounded-md border border-(--color-border) px-1.5 py-0.5 text-[11px]" />
          <button type="button" data-testid={`scripts-action-edit-${slotId}`}
            disabled={busy !== null || !editValue.trim()}
            onClick={async () => {
              const v = editValue.trim();
              // key persists for THIS payload (field+value+head); a retry reuses it, a changed value
              // starts a new identity, and success rotates it so the next edit is distinct.
              const key = keyFor(editKey, `final_line|${v}|${head}`);
              const ok = await post("edit", "edit",
                { field: "final_line", value: v, expected_revision: head, idempotency_key: key });
              if (ok) editKey.current = null;
            }}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "edit" ? "Editing…" : "Edit final line"}
          </button>
        </div>
      ) : denied("edit")}

      {/* REQUEST CHANGE — the API field is `comment` (the rework directive), NOT `reason`. */}
      {allowed("request_change") ? (
        <div className="flex flex-wrap items-center gap-1">
          <input data-testid={`scripts-rc-comment-${slotId}`} value={rcComment}
            onChange={(e) => setRcComment(e.target.value)} placeholder="change directive"
            className="rounded-md border border-(--color-border) px-1.5 py-0.5 text-[11px]" />
          <button type="button" data-testid={`scripts-action-request_change-${slotId}`}
            disabled={busy !== null || !rcComment.trim()}
            onClick={() => post("request_change", "request_change", { comment: rcComment.trim() })}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "request_change" ? "Sending…" : "Request change"}
          </button>
        </div>
      ) : denied("request_change")}

      {/* REWORK FROM HEAD — an explicit reviewer directive (`comment`); key minted at submit. */}
      {allowed("rework") ? (
        <div className="flex flex-wrap items-center gap-1">
          <input data-testid={`scripts-rework-comment-${slotId}`} value={reworkComment}
            onChange={(e) => setReworkComment(e.target.value)} placeholder="rework directive"
            className="rounded-md border border-(--color-border) px-1.5 py-0.5 text-[11px]" />
          <button type="button" data-testid={`scripts-action-rework-${slotId}`}
            disabled={busy !== null || !reworkComment.trim()}
            onClick={async () => {
              const c = reworkComment.trim();
              const key = keyFor(reworkKey, `rework|${c}|${head}`);
              const ok = await post("rework", "rework_from",
                { revision: head, comment: c, expected_revision: head, idempotency_key: key });
              if (ok) reworkKey.current = null;
            }}
            className="rounded-md border border-(--color-border) px-2 py-0.5 text-[11px]">
            {busy === "rework" ? "Reworking…" : "Rework from head"}
          </button>
        </div>
      ) : denied("rework")}

      {(refusal || notice) && (
        <p ref={statusRef} tabIndex={-1} role="status" aria-live="polite"
          data-testid={refusal ? `scripts-action-refusal-${slotId}` : `scripts-action-notice-${slotId}`}
          className="text-[11px] text-(--color-muted) outline-none">
          {refusal ? `refused: ${refusal}` : notice}
        </p>
      )}
    </div>
  );
}

function SlotRevisions({ slotId }: { slotId: string }) {
  // The `artifact=script` parameter is REQUIRED by V2's query boundary. If it were ever dropped the
  // request is refused (403) rather than silently answered with TOPIC history — see
  // lib/api-contract.ts resolveAllowedQuery.
  const revs = useRead<ScriptRevision[]>(
    `/gw/slots/${encodeURIComponent(slotId)}/revisions?artifact=script`,
  );
  return (
    <div data-testid={`scripts-revisions-${slotId}`} className="rounded-md border border-(--color-border) p-2">
      <div className="font-mono text-[11px]" data-testid={`scripts-slot-id-${slotId}`}>{slotId}</div>
      <SlotLifecycle slotId={slotId} />
      {revs.phase === "loading" && <p className="text-[11px] text-(--color-muted)">Loading…</p>}
      {revs.phase === "error" && (
        <p data-testid={`scripts-revisions-error-${slotId}`} className="text-[11px] text-(--color-muted)">
          No script history available — the server reported: {revs.detail}
        </p>
      )}
      {revs.phase === "ok" && revs.data.length === 0 && (
        <p data-testid={`scripts-revisions-empty-${slotId}`} className="text-[11px] text-(--color-muted)">
          No script revisions recorded for this slot.
        </p>
      )}
      {revs.phase === "ok" && revs.data.length > 0 && (
        <ol className="mt-1 flex flex-col gap-1">
          {revs.data.map((r) => (
            <li key={r.revision} data-testid={`scripts-rev-${slotId}-${r.revision}`} className="text-[11px]">
              <span className="font-mono">rev {r.revision}</span>
              {r.approved && <span data-testid={`scripts-rev-approved-${slotId}`} className="ml-1">· approved</span>}
              {r.model && <span className="ml-1 text-(--color-muted)">· {r.model}</span>}
              {r.needs_scholar_review && <span className="ml-1">· scholar review required</span>}
              {r.needs_native_review && <span className="ml-1">· native review required</span>}
              {r.body && <div className="mt-0.5 whitespace-pre-wrap text-(--color-muted)">{r.body}</div>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export type SlotsState =
  | { phase: "loading" }
  | { phase: "ok"; ids: readonly string[] }
  | { phase: "error"; detail: string };

export function ScriptsWorkspace(
  { roundId, gateStage, slots }: { roundId: string; gateStage: string; slots: SlotsState },
) {
  const [open, setOpen] = useState<string | null>(null);
  const toggle = useCallback((id: string) => setOpen((cur) => (cur === id ? null : id)), []);
  return (
    <div data-testid="scripts-workspace" data-round-id={roundId} data-gate-stage={gateStage} className="flex flex-col gap-2">
      <GenerationControl roundId={roundId} gateStage={gateStage} />
      <StageStatePanel roundId={roundId} gateStage={gateStage} />
      <section data-testid="scripts-slots" className="rounded-md border border-(--color-border) p-3 text-xs">
        <h3 className="font-semibold">Script history by slot</h3>
        {slots.phase === "loading" ? (
          <p data-testid="scripts-slots-loading" className="text-(--color-muted)">Loading the run…</p>
        ) : slots.phase === "error" ? (
          // NOT "no slots": a failed read is reported as a failed read.
          <p data-testid="scripts-slots-error" className="text-(--color-muted)">
            The run could not be read, so its slots are unavailable — the server reported: {slots.detail}
          </p>
        ) : slots.ids.length === 0 ? (
          <p data-testid="scripts-no-slots" className="text-(--color-muted)">
            This run has no slots to show script history for.
          </p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {slots.ids.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  data-testid={`scripts-slot-toggle-${id}`}
                  aria-expanded={open === id}
                  onClick={() => toggle(id)}
                  className="rounded-md border border-(--color-border) px-2 py-1 font-mono text-[11px]"
                >
                  {id}
                </button>
                {open === id && <SlotRevisions slotId={id} />}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
