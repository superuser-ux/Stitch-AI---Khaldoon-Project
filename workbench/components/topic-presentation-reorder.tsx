"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { readJson, ReadError, type RoundDetail, type SlotDetail } from "@/lib/read-model";

// #314 — governed Topic-workbench PRESENTATION reorder on the V2 workbench.
//
// Distinct from #292 Schedule order: it has its OWN token and is PRESENTATION ONLY — it never changes
// slot placement, schedule order/token, disposition, approval, taxonomy, config, or revision identity.
// Accessible NON-DRAG controls only (move earlier/later). A conflict — a stale token OR a concurrent-
// modification serialization conflict (both 409) — is resolved through an explicit refresh, never a
// silent overwrite. A round with no governed order yet (token 0) shows its slots in id order; the first
// apply mints generation 1 (presentation is cosmetic — no separate init slice needed).

type Presentation = {
  round_id: string;
  topic_presentation_token: number;
  legacy: boolean;
  positions: { slot_id: string; display_position: number }[];
};

export function TopicPresentationReorder({ roundId }: { roundId: string }) {
  const [pres, setPres] = useState<Presentation | null>(null);
  const [slots, setSlots] = useState<Record<string, SlotDetail>>({});
  const [baseOrder, setBaseOrder] = useState<string[]>([]);
  const [preview, setPreview] = useState<string[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  // #315 review finding 2 — after an apply settles, move focus to the announced role=status region
  // (success), the conflict notice, or the error notice, so a keyboard/AT user is never stranded when
  // the list re-renders. aria-live announces the settled outcome. No dialogs exist to dismiss.
  const statusRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!busy && (applied || conflict || err)) statusRef.current?.focus();
  }, [busy, applied, conflict, err]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setErr(null);
    try {
      const [p, d] = await Promise.all([
        readJson<Presentation>(`/gw/rounds/${encodeURIComponent(roundId)}/topic-presentation`),
        readJson<RoundDetail>(`/gw/rounds/${encodeURIComponent(roundId)}`),
      ]);
      if (mine !== seq.current) return;
      setPres(p);
      setSlots(Object.fromEntries(d.slots.map((s) => [s.slot_id, s])));
      const committed = p.positions.length
        ? [...p.positions].sort((a, b) => a.display_position - b.display_position).map((x) => x.slot_id)
        : [...d.slots.map((s) => s.slot_id)].sort();
      setBaseOrder(committed);
      setPreview(null);
      setConflict(null);
    } catch (e) {
      if (mine !== seq.current) return;
      setErr(e instanceof ReadError ? e.message : "read failed");
    }
  }, [roundId]);

  useEffect(() => { load(); }, [load]);

  const order = preview ?? baseOrder;
  const dirty = preview !== null && preview.join() !== baseOrder.join();

  const move = (index: number, delta: number) => {
    const next = [...order];
    const to = index + delta;
    if (to < 0 || to >= next.length) return;
    [next[index], next[to]] = [next[to], next[index]];
    setPreview(next);
    setConflict(null);
    setApplied(null);   // a new edit supersedes any prior applied-notice
  };

  const commit = async () => {
    if (!pres || !preview) return;
    setBusy(true); setConflict(null); setErr(null); setApplied(null);
    try {
      const res = await fetch(`/gw/rounds/${encodeURIComponent(roundId)}/topic-presentation-reorder`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ order: preview, topic_presentation_token: pres.topic_presentation_token }),
      });
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown; current_token?: number | null };
      if (res.status === 409) {
        const cur = body?.current_token;
        setConflict(
          `The presentation order changed while you were reordering (your version ` +
            `${pres.topic_presentation_token}${cur != null ? `, current ${cur}` : ""}). ` +
            `Refresh to see the accepted order, then re-apply.`,
        );
        return;
      }
      if (!res.ok) {
        setErr(body?.detail ? String(body.detail) : `reorder failed (${res.status})`);
        return;
      }
      await load();
      setApplied("Presentation order applied — the governed version advanced.");
    } catch {
      setErr("tanaghom api unreachable");
    } finally {
      setBusy(false);
    }
  };

  if (err) {
    return (
      <div ref={statusRef} tabIndex={-1} role="alert" aria-live="assertive"
        data-testid="wb-tpres-error" className="rounded-xl border border-(--color-border) bg-(--color-card) p-3 text-xs text-(--color-danger) outline-none">
        <p className="mb-2">Could not read the presentation order: {err}</p>
        <button data-testid="wb-tpres-retry" onClick={load}
          className="rounded-md border border-(--color-border) px-2 py-1 font-medium text-(--color-fg)">Retry</button>
      </div>
    );
  }
  if (!pres) {
    return <p data-testid="wb-tpres-loading" className="text-xs text-(--color-muted)">Loading presentation order…</p>;
  }

  return (
    <div data-testid="wb-tpres" className="rounded-xl border border-(--color-border) bg-(--color-card) p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-(--color-muted)">Topic presentation order</h2>
        <span data-testid="wb-tpres-token" className="rounded-full border border-(--color-border) px-2 py-0.5 text-[10px] text-(--color-muted)">
          version {pres.topic_presentation_token}
        </span>
        <span data-testid="wb-tpres-scope-note" className="text-[10px] text-(--color-muted)">presentation only — never changes schedule, disposition, or content</span>
        {dirty && (
          <span data-testid="wb-tpres-preview-badge" className="rounded-full border border-(--color-warn) px-2 py-0.5 text-[10px] font-medium text-(--color-warn)">
            unsaved preview — not applied
          </span>
        )}
      </div>

      {conflict && (
        <div ref={statusRef} tabIndex={-1} role="alert" aria-live="assertive"
          data-testid="wb-tpres-conflict" className="mb-2 rounded-lg border border-(--color-warn) px-3 py-2 text-xs text-(--color-warn) outline-none">
          <p className="mb-2">{conflict}</p>
          <button data-testid="wb-tpres-refresh" onClick={load}
            className="rounded-md border border-(--color-border) px-2 py-1 font-medium text-(--color-fg)">Refresh</button>
        </div>
      )}
      {applied && !conflict && (
        <div ref={statusRef} tabIndex={-1} role="status" aria-live="polite"
          data-testid="wb-tpres-status" className="mb-2 rounded-lg border border-(--color-ok) px-3 py-2 text-xs text-(--color-ok) outline-none">
          {applied}
        </div>
      )}

      <ol data-testid="wb-tpres-list" className="flex flex-col gap-2">
        {order.map((sid, i) => {
          const slot = slots[sid];
          return (
            <li key={sid} data-testid={`wb-tpres-${sid}`}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-(--color-border) px-3 py-2">
              <span className="w-6 shrink-0 text-center text-[11px] text-(--color-muted)">{i + 1}</span>
              <span data-testid={`wb-tpres-slot-${sid}`} className="font-mono text-xs font-medium">{sid}</span>
              <span className="min-w-0 flex-1 truncate text-[11px] text-(--color-muted)">
                {[slot?.format, slot?.status].filter(Boolean).join(" · ")}
              </span>
              <span className="flex shrink-0 gap-1">
                <button data-testid={`wb-tpres-up-${sid}`} onClick={() => move(i, -1)} disabled={i === 0}
                  aria-label={`Move ${sid} earlier`}
                  className="rounded-md border border-(--color-border) px-2 py-1 text-xs disabled:opacity-40">↑</button>
                <button data-testid={`wb-tpres-down-${sid}`} onClick={() => move(i, 1)} disabled={i === order.length - 1}
                  aria-label={`Move ${sid} later`}
                  className="rounded-md border border-(--color-border) px-2 py-1 text-xs disabled:opacity-40">↓</button>
              </span>
            </li>
          );
        })}
      </ol>

      <div className="mt-3 flex gap-2">
        <button data-testid="wb-tpres-apply" onClick={commit} disabled={!dirty || busy}
          className="rounded-md border border-(--color-border) bg-(--color-bg) px-3 py-1.5 text-xs font-medium disabled:opacity-40">
          {busy ? "Applying…" : "Apply order"}
        </button>
        <button data-testid="wb-tpres-discard" onClick={() => { setPreview(null); setConflict(null); }}
          disabled={!dirty || busy}
          className="rounded-md border border-(--color-border) px-3 py-1.5 text-xs disabled:opacity-40">
          Discard preview
        </button>
      </div>
    </div>
  );
}
