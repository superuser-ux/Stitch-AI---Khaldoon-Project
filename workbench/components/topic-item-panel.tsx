"use client";

// #313 Stage 2B-1 — the canonical per-item Topic governance surface. It renders ONE server-owned read
// model (GET /slots/{id}/topic_item): status, head/approved revision, the immutable append-only
// revision history (parent/base lineage + approved flag), and the TYPED action map. It offers only the
// actions the server marks allowed — a denied action shows the server's machine reason, never a bare
// hide and never a client-side eligibility guess. The one write it drives (structured edit of the
// source-language field) goes through V2's allowlisted /gw seam with an expected-revision CAS; a typed
// 409 (stale_revision / governed_denial) is relayed verbatim. V2 mints no authority and rewrites no
// language truth: source Arabic is shown with correct dir + bidi isolation, and a missing source is
// DISCLOSED, never fabricated.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  readJson,
  postJson,
  ReadError,
  WriteError,
  type TopicItemReadModel,
} from "@/lib/read-model";
import { BilingualText } from "./bilingual-text";

/** Render a source-language (Arabic) value with correct direction + bidi isolation, or DISCLOSE its
 *  absence. Never fabricates or normalizes the source. */
function SourceText({ value, slotId }: { value?: string | null; slotId: string }) {
  if (value == null || value === "") {
    return (
      <span
        data-testid={`wb-topic-item-missing-lang-${slotId}`}
        className="text-[11px] italic text-(--color-muted)"
      >
        source language missing — not fabricated
      </span>
    );
  }
  // `bdi` + dir="auto" isolate the run so mixed LTR/RTL neighbours never reorder it (#313 source truth).
  // #315 — truthful per-node lang: the source angle field is Arabic (`text_ar`).
  return (
    <bdi lang="ar" dir="auto" className="text-sm text-(--color-fg)">
      {value}
    </bdi>
  );
}

export default function TopicItemPanel({ slotId }: { slotId: string }) {
  const [model, setModel] = useState<TopicItemReadModel | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [comment, setComment] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // #315 — focus restoration: after a command settles, move focus to the announced status region so a
  // keyboard/AT user is never stranded when the list re-renders (there are no dialogs/traps). The region
  // is role=status aria-live so the outcome is also announced.
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (msg && !busy) statusRef.current?.focus();
  }, [msg, busy]);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const m = await readJson<TopicItemReadModel>(`/gw/slots/${encodeURIComponent(slotId)}/topic_item`, signal);
      setModel(m);
      setErr(null);
    } catch (e) {
      if ((e as Error)?.name === "AbortError") return;
      setErr(e instanceof ReadError ? `${e.status}: ${e.message}` : "read failed");
    }
  }, [slotId]);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const editAction = model?.actions?.edit;

  const save = useCallback(async () => {
    if (!model || !draft.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      // expected_revision = the head we read: an optimistic-concurrency CAS. If it is stale the server
      // answers 409 stale_revision and we refresh — never a silent overwrite. idempotency_key makes a
      // double-submit return the original revision (visible B2 tokens on the wire).
      await postJson(`/gw/slots/${encodeURIComponent(slotId)}/edit`, {
        artifact: "topic",
        field: "text_ar",
        // #315 ruling 2 (Option B) — transmit the RAW draft bytes. `draft.trim()` is used ONLY as the
        // non-empty submit predicate (line 71); V2 applies NO client normalization to the source value.
        // The shared server's edit_revision canonicalizes (strip()) — pre-existing V1/backend behavior
        // #315 does not alter — so the PERSISTED value is the server-canonicalized form, not the raw
        // whitespace. Proven + disclosed by the byte e2e (raw on the wire; canonicalized value persisted).
        value: draft,
        expected_revision: model.head_revision,
        idempotency_key: crypto.randomUUID(),
      });
      setDraft("");
      setMsg("edit saved as a new revision");
      await load();
    } catch (e) {
      if (e instanceof WriteError) {
        if (e.error === "stale_revision") {
          setMsg(`someone else edited this — refreshed to rev ${e.current}. Review and re-apply.`);
          await load();
        } else if (e.error === "governed_denial") {
          setMsg(`edit refused: ${e.reason} — reopening needs governed reconsideration (#249)`);
          await load();
        } else {
          setMsg(`edit refused (${e.status}): ${e.message}`);
        }
      } else {
        setMsg("edit failed");
      }
    } finally {
      setBusy(false);
    }
  }, [model, draft, slotId, load]);

  // Generic governed-action runner for the rest of the family (rework / drop / request_change /
  // approve). Each button is offered ONLY when the server's typed action map marks it allowed; the
  // server owns the decision and V2 relays the typed refusal verbatim — it mints no authority.
  const runAction = useCallback(async (verb: string, body: unknown, okMsg: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await postJson(`/gw/slots/${encodeURIComponent(slotId)}/${verb}`, body);
      setMsg(okMsg);
      setComment("");
      await load();
    } catch (e) {
      if (e instanceof WriteError) {
        if (e.error === "governed_denial") {
          setMsg(`refused: ${e.reason} — reconsideration (#249) is unavailable`);
          await load();
        } else if (e.error === "stale_revision") {
          setMsg(`stale — refreshed to rev ${e.current}. Review and re-apply.`);
          await load();
        } else {
          setMsg(`refused (${e.status}): ${e.message}`);
        }
      } else {
        setMsg("action failed");
      }
    } finally {
      setBusy(false);
    }
  }, [slotId, load]);

  // #373 (Codex ruling 2) — gate-scoped pre-commit UNDO. undecide is addressed to an EXACT gate id;
  // V2 consumes the server-projected `authoritative_gate_id` DIRECTLY and never derives/sorts/chooses a
  // gate. When the server does not project exactly one applicable gate the id is null and the control
  // renders typed-unavailable (from actions.undecide.reason) rather than guessing.
  const clearUndo = useCallback(async () => {
    const gid = model?.authoritative_gate_id;
    if (!gid) return;
    setBusy(true);
    setMsg(null);
    try {
      await postJson(`/gw/gates/${encodeURIComponent(gid)}/undecide`, { slot_ids: [slotId] });
      setMsg("decision cleared (pre-commit undo)");
      await load();
    } catch (e) {
      if (e instanceof WriteError) {
        // already submitted / no decision / mismatch -> typed, NON-mutating refusal relayed verbatim.
        setMsg(`clear refused (${e.status}): ${e.error ?? e.message}`);
        await load();
      } else {
        setMsg("clear failed");
      }
    } finally {
      setBusy(false);
    }
  }, [model, slotId, load]);

  if (err) {
    return (
      <p data-testid={`wb-topic-item-error-${slotId}`} className="mt-2 text-[11px] text-(--color-danger)">
        Could not read per-item governance: {err}
      </p>
    );
  }
  if (!model) {
    return (
      <p data-testid={`wb-topic-item-loading-${slotId}`} className="mt-2 text-[11px] text-(--color-muted)">
        Loading item governance…
      </p>
    );
  }

  return (
    <section
      data-testid={`wb-topic-item-${slotId}`}
      className="mt-2 rounded-lg border border-(--color-border) bg-(--color-bg) px-3 py-2"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-(--color-muted)">
        <span className="font-medium text-(--color-fg)">Per-item governance</span>
        <span data-testid={`wb-topic-item-status-${slotId}`}>{model.status ?? "—"}</span>
        <span data-testid={`wb-topic-item-head-${slotId}`}>head rev {model.head_revision}</span>
        <span data-testid={`wb-topic-item-approved-${slotId}`}>
          approved {model.approved_revision ?? "none"}
        </span>
      </div>

      {/* Explicit identity disclosure — slot_id is the STABLE per-item key; topic_id is per-revision
          (shown per row below), never conflated. (#313 Codex blocker 4.) */}
      <p
        data-testid={`wb-topic-item-identity-${slotId}`}
        data-stable-key={model.identity?.stable_key ?? "slot_id"}
        title={model.identity?.note}
        className="mt-0.5 font-mono text-[10px] text-(--color-muted)"
      >
        item {model.identity?.stable_key ?? "slot_id"}={model.identity?.slot_id ?? slotId} · topic_id
        is per-revision
      </p>

      {/* immutable append-only history + parent/base lineage */}
      <ul data-testid={`wb-topic-item-history-${slotId}`} className="mt-1.5 flex flex-col gap-1">
        {model.revisions.map((rev) => (
          <li
            key={rev.revision}
            data-testid={`wb-topic-item-rev-${slotId}-${rev.revision}`}
            className="flex flex-wrap items-baseline gap-x-2 text-[11px]"
          >
            <span className="font-mono text-(--color-muted)">
              rev {rev.revision}
              {rev.base_revision ? ` ← ${rev.base_revision}` : ""}
            </span>
            {rev.topic_id && (
              <span
                className="font-mono text-[10px] text-(--color-muted)"
                title="per-revision topic_id (immutable for this revision; not stable across revisions)"
              >
                {rev.topic_id.slice(0, 8)}
              </span>
            )}
            {rev.approved && (
              <span
                data-testid={`wb-topic-item-approved-badge-${slotId}`}
                className="rounded-full border border-(--color-border) px-1.5 text-[10px] text-(--color-fg)"
              >
                approved
              </span>
            )}
            <SourceText value={rev.body} slotId={`${slotId}-${rev.revision}`} />
            {/* #315 ruling 1 — the canonical bilingual pair exposed on a revision: the rework change
                summary. Rendered in its deterministic 4-state presentation with truthful per-node
                lang/dir. The `missing` state (neither side present) is DISCLOSED, never hidden: absence
                of UI would silently redefine "missing" as "not shown", so the component is mounted
                unconditionally and it emits data-bilingual-state="missing" + the explicit disclosure. */}
            <div className="mt-1 border-s-2 border-(--color-border) ps-2">
              <span className="text-[10px] uppercase tracking-wide text-(--color-muted)">change summary</span>
              <BilingualText
                ar={rev.change_summary_ar}
                en={rev.change_summary_en}
                testid={`wb-topic-item-change-summary-${slotId}-${rev.revision}`}
              />
            </div>
          </li>
        ))}
      </ul>

      {/* the one write: structured edit of the source-language field, gated by the TYPED action */}
      <div className="mt-2 border-t border-(--color-border) pt-2">
        {editAction?.allowed ? (
          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] text-(--color-muted)" htmlFor={`edit-${slotId}`}>
              Structured edit — source angle (text_ar), appended as a new revision
            </label>
            <textarea
              id={`edit-${slotId}`}
              data-testid={`wb-topic-item-edit-${slotId}`}
              dir="auto"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-[3rem] w-full rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-sm text-(--color-fg)"
              placeholder="new source-language value…"
            />
            <button
              type="button"
              data-testid={`wb-topic-item-edit-save-${slotId}`}
              disabled={busy || !draft.trim()}
              onClick={save}
              className="self-start rounded-md border border-(--color-border) px-2 py-1 text-xs font-medium text-(--color-fg) hover:bg-(--color-bg) disabled:opacity-50"
            >
              Save as new revision
            </button>
          </div>
        ) : (
          <p
            data-testid={`wb-topic-item-edit-denied-${slotId}`}
            data-reason={editAction?.reason ?? "unavailable"}
            className="text-[11px] text-(--color-muted)"
          >
            Editing is not available for this item ({editAction?.reason ?? "unavailable"}) — a governed
            action on the authorized surface.
          </p>
        )}

        {/* #313 — the rest of the governed action family, each offered ONLY when the server's typed
            action map marks it allowed. A denied action stays visible but disabled with its reason. */}
        <div data-testid={`wb-topic-item-actions-${slotId}`} className="mt-2 flex flex-col gap-1.5">
          <input
            data-testid={`wb-topic-item-comment-${slotId}`}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            dir="auto"
            placeholder="rationale (for send-back / rework)…"
            className="w-full rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs text-(--color-fg)"
          />
          <div className="flex flex-wrap gap-1.5">
            {(
              [
                { key: "approve", label: "Approve", run: () => runAction("approve", { expected_revision: model.head_revision }, "approval decision recorded for this revision (advances at the human commit)") },
                { key: "request_change", label: "Send back", needsComment: true, run: () => runAction("request_change", { comment: comment.trim() }, "change-request decision recorded (advances at the human commit)") },
                { key: "rework", label: "Rework", needsComment: true, run: () => runAction("rework_from", { artifact: "topic", revision: model.head_revision, comment: comment.trim(), expected_revision: model.head_revision, idempotency_key: crypto.randomUUID() }, "reworking from head") },
                { key: "drop", label: "Drop", run: () => runAction("drop", {}, "drop (reject) decision recorded (advances at the human commit)") },
                // #373 (Codex ruling 1) — canonical `reopen`: reverse a COMMITTED decision (un-reject a
                // dropped item / un-approve) back into review. The label maps 1:1 to the reopen endpoint;
                // it is DISTINCT from `restore` (restore_revision) and never a semantic alias.
                { key: "reopen", label: "Reopen", run: () => runAction("reopen", {}, "reopened into review (committed decision reversed)") },
              ] as const
            ).map((a) => {
              const act = model.actions?.[a.key];
              const needsComment = "needsComment" in a && a.needsComment;
              return (
                <button
                  key={a.key}
                  type="button"
                  data-testid={`wb-topic-item-action-${a.key}-${slotId}`}
                  data-allowed={act?.allowed ? "true" : "false"}
                  data-reason={act?.reason ?? ""}
                  disabled={busy || !act?.allowed || (needsComment && !comment.trim())}
                  onClick={a.run}
                  title={act?.allowed ? undefined : `not available: ${act?.reason ?? "unavailable"}`}
                  className="rounded-md border border-(--color-border) px-2 py-1 text-xs font-medium text-(--color-fg) hover:bg-(--color-bg) disabled:opacity-50"
                >
                  {a.label}
                </button>
              );
            })}
            {/* #373 (Codex ruling 2) — pre-commit UNDO (clear the recorded decision), addressed to the
                server-projected authoritative gate id. Visible-but-disabled with the typed reason when
                unavailable (no open gate / ambiguous / no decision); never a client gate choice. */}
            {(() => {
              const u = model.actions?.undecide;
              return (
                <button
                  type="button"
                  data-testid={`wb-topic-item-action-undecide-${slotId}`}
                  data-allowed={u?.allowed ? "true" : "false"}
                  data-reason={u?.reason ?? ""}
                  data-gate={model.authoritative_gate_id ?? ""}
                  disabled={busy || !u?.allowed || !model.authoritative_gate_id}
                  onClick={clearUndo}
                  title={u?.allowed ? undefined : `not available: ${u?.reason ?? "unavailable"}`}
                  className="rounded-md border border-(--color-border) px-2 py-1 text-xs font-medium text-(--color-fg) hover:bg-(--color-bg) disabled:opacity-50"
                >
                  Undo decision
                </button>
              );
            })()}
          </div>
        </div>

        {msg && (
          <p ref={statusRef} tabIndex={-1} role="status" aria-live="polite"
             data-testid={`wb-topic-item-write-msg-${slotId}`} className="mt-1 text-[11px] text-(--color-fg) outline-none">
            {msg}
          </p>
        )}
      </div>
    </section>
  );
}
