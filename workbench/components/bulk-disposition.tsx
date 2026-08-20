"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  readJson, ReadError, postJson, WriteError,
  type RoundDetail, type TopicItemReadModel,
} from "@/lib/read-model";

// #314 — governed BULK Topic disposition on the V2 workbench.
//
// The reviewer selects items, chooses ONE closed action (approve / request_change / drop), and submits a
// single governed bulk operation through the allowlisted /gw seam. The SERVER maps each item to the
// existing canonical per-item command under an exact-revision CAS + fail-closed authority/eligibility,
// and returns a TRUTHFUL per-item outcome ledger. V2 renders each typed outcome verbatim
// (succeeded / stale / denied / conflicted / not_attempted) with the server's machine reason; it mints
// no authority, advances/pins nothing, and reinterprets nothing. A whole-request refusal (unsigned,
// bad action, membership) is relayed as its typed WriteError.

type Item = { slot_id: string; head_revision: number; status: string };
type Outcome = { slot_id: string; outcome: string | null; reason: string | null };
type BulkResult = { state: string; resolution?: string; items: Outcome[] };

const ACTIONS = [
  { key: "bulk_approve", label: "Approve" },
  { key: "bulk_request_change", label: "Request change" },
  { key: "bulk_drop", label: "Drop (recoverable)" },
] as const;

const OUTCOME_STYLE: Record<string, string> = {
  succeeded: "border-(--color-ok) text-(--color-ok)",
  stale: "border-(--color-warn) text-(--color-warn)",
  denied: "border-(--color-danger) text-(--color-danger)",
  conflicted: "border-(--color-warn) text-(--color-warn)",
  not_attempted: "border-(--color-border) text-(--color-muted)",
};

let _key = 0;

export function BulkDisposition({ roundId }: { roundId: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [action, setAction] = useState<string>("bulk_approve");
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<BulkResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  // Retry-stable idempotency: ONE key for the immutable selection/action/comment/revision payload,
  // reused across timeout/unknown-response retries (so a retry recovers the SAME batch, one effect); a
  // new key is minted ONLY when the payload changes OR the prior operation terminally settled.
  const keyRef = useRef<string | null>(null);
  const keySigRef = useRef<string | null>(null);
  const settledRef = useRef(false);
  // #315 review finding 2 — after a bulk command settles, move focus to the announced role=status
  // region so a keyboard/AT user is never stranded when the list re-renders (there are no dialogs to
  // dismiss). The region is aria-live so the settled outcome (the per-item ledger summary, or a typed
  // whole-request refusal) is also announced.
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (!busy && (result || err)) statusRef.current?.focus();
  }, [busy, result, err]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setErr(null);
    try {
      const d = await readJson<RoundDetail>(`/gw/rounds/${encodeURIComponent(roundId)}`);
      const candidates = d.slots.filter((s) => /TOPIC|CHANGE/i.test(s.status || ""));
      const heads = await Promise.all(candidates.map(async (s) => {
        try {
          const m = await readJson<TopicItemReadModel>(`/gw/slots/${encodeURIComponent(s.slot_id)}/topic_item`);
          return { slot_id: s.slot_id, head_revision: m.head_revision, status: m.status } as Item;
        } catch {
          return null;
        }
      }));
      if (mine !== seq.current) return;
      setItems(heads.filter((x): x is Item => x !== null));
      setSelected(new Set());
    } catch (e) {
      if (mine !== seq.current) return;
      setErr(e instanceof ReadError ? e.message : "read failed");
    }
  }, [roundId]);

  useEffect(() => { load(); }, [load]);

  const toggle = (sid: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(sid)) n.delete(sid); else n.add(sid);
      return n;
    });

  const submit = async () => {
    if (!selected.size) return;
    if (action === "bulk_request_change" && !comment.trim()) {
      setErr("Request change needs a comment for the whole selection.");
      return;
    }
    setBusy(true); setErr(null); setResult(null);
    try {
      const chosen = items
        .filter((it) => selected.has(it.slot_id))
        .sort((a, b) => a.slot_id.localeCompare(b.slot_id));
      const payload = {
        action,
        items: chosen.map((it) => ({ slot_id: it.slot_id, expected_revision: it.head_revision })),
        comment: action === "bulk_request_change" ? comment.trim() : null,
      };
      const sig = JSON.stringify(payload);
      if (keyRef.current === null || keySigRef.current !== sig || settledRef.current) {
        keyRef.current = globalThis.crypto?.randomUUID?.() ?? `bulk-${roundId}-${Date.now()}-${++_key}`;
        keySigRef.current = sig;
        settledRef.current = false;   // a fresh operation — retries until it terminally settles reuse it
      }
      const res = await postJson<BulkResult>(`/gw/rounds/${encodeURIComponent(roundId)}/bulk-operations`, {
        ...payload,
        idempotency_key: keyRef.current,
      });
      settledRef.current = true;       // terminal success -> a later same-payload submit is a NEW op
      setResult(res);
      await load();
    } catch (e) {
      if (e instanceof WriteError) setErr(`${e.error ?? "denied"}: ${e.message}`);
      else setErr("bulk disposition failed");
    } finally {
      setBusy(false);
    }
  };

  if (err && !items.length && !result) {
    return (
      <div data-testid="wb-bulk-error" className="rounded-xl border border-(--color-border) bg-(--color-card) p-3 text-xs text-(--color-danger)">
        <p className="mb-2">Bulk disposition: {err}</p>
        <button data-testid="wb-bulk-retry" onClick={load}
          className="rounded-md border border-(--color-border) px-2 py-1 font-medium text-(--color-fg)">Retry</button>
      </div>
    );
  }

  return (
    <div data-testid="wb-bulk" className="rounded-xl border border-(--color-border) bg-(--color-card) p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-(--color-muted)">Bulk disposition</h2>
        <span data-testid="wb-bulk-selected" className="rounded-full border border-(--color-border) px-2 py-0.5 text-[10px] text-(--color-muted)">
          {selected.size} selected
        </span>
      </div>

      {items.length === 0 ? (
        <p data-testid="wb-bulk-empty" className="text-xs text-(--color-muted)">No Topic items in review for this run.</p>
      ) : (
        <ul data-testid="wb-bulk-list" className="mb-3 flex flex-col gap-1.5">
          {items.map((it) => {
            const oc = result?.items.find((o) => o.slot_id === it.slot_id);
            return (
              <li key={it.slot_id} data-testid={`wb-bulk-row-${it.slot_id}`}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-(--color-border) px-3 py-1.5">
                <input type="checkbox" data-testid={`wb-bulk-select-${it.slot_id}`}
                  checked={selected.has(it.slot_id)} onChange={() => toggle(it.slot_id)}
                  aria-label={`Select ${it.slot_id}`} />
                <span className="font-mono text-xs font-medium">{it.slot_id}</span>
                <span className="text-[10px] text-(--color-muted)">head rev {it.head_revision} · {it.status}</span>
                {oc?.outcome && (
                  <span data-testid={`wb-bulk-outcome-${it.slot_id}`}
                    title={oc.reason ?? undefined}
                    className={`ml-auto rounded-full border px-2 py-0.5 text-[10px] font-medium ${OUTCOME_STYLE[oc.outcome] ?? "border-(--color-border) text-(--color-muted)"}`}>
                    {oc.outcome}{oc.reason ? ` · ${oc.reason}` : ""}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[11px] text-(--color-muted)" htmlFor="wb-bulk-action">Action</label>
        <select id="wb-bulk-action" data-testid="wb-bulk-action" value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs">
          {ACTIONS.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
        </select>
        <button data-testid="wb-bulk-apply" onClick={submit} disabled={!selected.size || busy}
          className="rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-1.5 text-xs font-medium disabled:opacity-40">
          {busy ? "Applying…" : `Apply to ${selected.size}`}
        </button>
      </div>

      {action === "bulk_request_change" && (
        // bidi-aware: the reviewer comment may be Arabic; render it dir="auto" so a mixed/RTL comment
        // displays correctly (the workbench chrome is LTR, content is direction-detected per element).
        <textarea data-testid="wb-bulk-comment" dir="auto" value={comment} onChange={(e) => setComment(e.target.value)}
          placeholder="Shared change request for the whole selection (required)"
          className="mt-2 w-full rounded-md border border-(--color-border) bg-(--color-bg) px-2 py-1 text-xs" rows={2} />
      )}

      {result && (
        <p ref={statusRef} tabIndex={-1} role="status" aria-live="polite"
           data-testid="wb-bulk-result" className="mt-2 text-[11px] text-(--color-muted) outline-none">
          Batch {result.state}
          {result.resolution ? ` (${result.resolution})` : ""} — per-item outcomes shown above; each is the
          server&apos;s truthful result (succeeded / stale / denied / conflicted / not&nbsp;attempted).
        </p>
      )}
      {err && result === null && items.length > 0 && (
        <p ref={statusRef} tabIndex={-1} role="alert" aria-live="assertive"
           data-testid="wb-bulk-inline-error" className="mt-2 text-[11px] text-(--color-danger) outline-none">{err}</p>
      )}
    </div>
  );
}
