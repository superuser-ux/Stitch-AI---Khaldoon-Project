"use client";

// #304 Stage 1, Level 2 — the selected-run governed Schedule workspace.
//
// AUTHORITY SPLIT (the reason this file is careful):
//   Tanaghom decides EVERYTHING. Which fields are revisable is its list, not ours
//   (_SCHEDULE_REVISION_FIELDS = day, time_uae, format, topic_guidance). Eligibility comes from the
//   run's PINNED policy generation, not the current catalogue. Authority, the token, and the
//   downstream freeze are its calls. This surface proposes, then renders what came back.
//
//   V2 validates nothing. It does not pre-filter a refusal into a nicer message, and it does not
//   hide a control to avoid a "no" — a hidden control silently asserts an authority model, and the
//   server's actual answer is the only truth about what is allowed.
//
// IDENTITY (#304): server-owned `display_code` is the ROUTINE identifier. Canonical `slot_id` stays
// visible as secondary diagnostic metadata — never invented, never parsed, never derived here.
//
// ORDER: the accepted order is the server's mapping. A drag or a keyboard move builds a PREVIEW and
// nothing more. Until the server accepts, the preview is a proposal — so a rejection reverts to the
// last authoritative order and re-reads, rather than leaving a local shadow order on screen.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { readJson, ReadError, type RoundDetail } from "@/lib/read-model";
import { adaptiveView, readViewState, runWindow, writeViewState, type ViewState } from "./schedule-views";
import { ScheduleViewToolbar } from "./schedule-view-toolbar";
import { RunScheduleCalendar } from "./run-schedule-calendar";
import type { LensKey } from "@/lib/shell-lens";

type Position = { slot_id: string; display_code: string; display_position: number };
type Mapping = { schedule_token: number; legacy: boolean; positions: Position[] };
type Slot = {
  slot_id: string; day?: number; time_uae?: string | null; format?: string | null;
  status?: string | null; pillar_code?: string | null; hcs_id?: string | null;
};
/** #304 — the run's PINNED eligible set. Each entry is an OBJECT carrying the framework's identity
 *  and the version it was pinned at; `name` is what the governed revision contract validates against
 *  (same as format_mix). Rendering the object itself is React error #31 — and pinning by name keeps
 *  V2 from inventing an identity the server does not use. */
type PinnedFormat = { name: string; version_id?: string; framework_id?: string };
/** #306 — the run's PINNED dependent taxonomy. Each HCS carries its own `pillar_code`, so the
 *  dependency is resolved by FILTERING server truth — never by inferring membership from a label,
 *  and never from the live catalogue (a run is not reinterpreted against a later catalogue).
 *  A legacy run with no pinned generation reports empty; the controls then have nothing truthful to
 *  offer and are not rendered. There is deliberately NO `category`: no canonical category identity
 *  exists, so it stays a derived HCS label with no persistence or authority of its own. */
type PinnedTaxonomy = {
  methodology_version: string | null;
  pillars: { pillar_code: string; code_short?: string; name_en?: string }[];
  hcs: { hcs_id: string; pillar_code: string; seq_in_pillar?: number; name_en?: string }[];
};
type Detail = RoundDetail & {
  slots?: Slot[]; pinned_eligible_formats?: PinnedFormat[]; pinned_taxonomy?: PinnedTaxonomy;
};

type Feedback = { kind: "idle" | "busy" | "ok" | "error" | "conflict"; msg?: string };

export function RunScheduleWorkspace({ roundId, lens: lensProp }: { roundId: string; lens: LensKey | null }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fb, setFb] = useState<Feedback>({ kind: "idle" });
  /** Proposed order. null = showing the server's accepted order. */
  const [preview, setPreview] = useState<string[] | null>(null);
  /** #306 — unsaved taxonomy proposal per slot: slot_id -> {pillar, hcs}. A draft is a PROPOSAL,
   *  never applied locally: the surface keeps showing server truth until the server accepts. */
  const [taxDraft, setTaxDraft] = useState<Record<string, { pillar: string; hcs: string }>>({});
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  // #385 scope 1 — visible drag STATE for the Schedule List. `dragId` marks the row being dragged
  // (drag-start state); `dropTargetId` marks the row currently under the pointer (valid-target state).
  // These drive only presentation (data-attributes + ring/opacity) — the ordering MODEL is unchanged:
  // a drag still only builds the same `preview` proposal that Apply order commits with the token.
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);
  const seq = useRef(0);
  // #373 (focus restoration, scoped per preflight) — the order-preview Apply/Discard controls UNMOUNT on
  // a successful commit (setPreview(null)); without this, keyboard/AT focus would fall to <body>. Move
  // focus to the announced feedback region (role=status aria-live) after any settled outcome. Local
  // pattern only; no shell/global change.
  const fbRef = useRef<HTMLDivElement>(null);
  // #373 (Codex P2) — restore focus ONLY on a SETTLED outcome (ok/error/conflict). During `busy`
  // (pending) focus is intentionally RETAINED on the initiating control, so a keyboard/AT user is not
  // yanked mid-operation; it moves to the announced region once the action settles.
  useEffect(() => {
    if (fb.kind === "ok" || fb.kind === "error" || fb.kind === "conflict") fbRef.current?.focus();
  }, [fb]);

  // #308 — this run's view/range is scoped by roundId in the URL, so it is shareable/restorable and
  // NEVER leaks across runs (each scope reads only its own keys). The initial view is the DETERMINISTIC
  // adaptive one, derived from the run's period_len_days once detail loads — not viewport guesswork.
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const scope = roundId;
  const defaultView = detail ? adaptiveView(detail.starts_on, detail.period_len_days) : "list";
  const explicit = params?.get(`v_${scope}`);
  const viewState = readViewState(new URLSearchParams(params?.toString() ?? ""), scope, defaultView);
  const setViewState = useCallback((next: ViewState) => {
    const qs = writeViewState(new URLSearchParams(params?.toString() ?? ""), scope, next);
    router.replace(`${pathname}?${qs.toString()}`, { scroll: false });
  }, [params, router, pathname, scope]);
  // If the operator hasn't chosen a view, keep reflecting the adaptive default as detail loads.
  const adaptiveEffective: ViewState = explicit ? viewState : { ...viewState, view: defaultView };

  // #376 RNG-01 — `?focus=range` asks this workspace to open ON THE RUN'S OWN accepted span. The
  // window is resolved from the SERVER's `starts_on`/`period_len_days`, never from what the composer
  // proposed: if the planner normalized anything, the operator sees what was ACCEPTED. An explicit
  // view choice in the URL always wins, so focusing never overrides a deliberate selection, and the
  // adaptive default is unchanged for every run opened without the flag.
  const focusRange = params?.get("focus") === "range";
  const effectiveView: ViewState = useMemo(() => {
    if (explicit || !focusRange || !detail?.starts_on) return adaptiveEffective;
    const w = runWindow(detail.starts_on, detail.period_len_days);
    if (!w) return adaptiveEffective;
    const lastInclusive = new Date(`${w.endExclusive}T00:00:00Z`);
    lastInclusive.setUTCDate(lastInclusive.getUTCDate() - 1);
    return { view: "range", rangeStart: w.start, rangeEnd: lastInclusive.toISOString().slice(0, 10) };
  }, [explicit, focusRange, detail?.starts_on, detail?.period_len_days, adaptiveEffective.view,
      adaptiveEffective.rangeStart, adaptiveEffective.rangeEnd]);

  // #376 VIEW-01 / #382 — the presentation LENS: Calendar, Grid and List are three projections of ONE
  // authoritative slot collection. All three render from the same `shown` array, in the same order,
  // with the same canonical `slot_id`s — no per-lens fetch, sort or copy, so they cannot diverge.
  // #382 (ruling 2): the lens is now resolved by the ONE shared shell-nav authority and passed in; the
  // TOP LENS MENU in the containment shell owns selection (writing `lens_{roundId}`, the same per-run
  // scoped key as before). This workspace no longer resolves or toggles the lens itself — it consumes
  // the resolved value and renders the matching projection. Switching issues no upstream request.
  const lens: "calendar" | "grid" | "list" =
    lensProp === "grid" ? "grid" : lensProp === "list" ? "list" : "calendar";

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const latest = () => mine === seq.current;   // #286 — only the newest read may commit
    setErr(null);
    try {
      const [d, m] = await Promise.all([
        readJson<Detail>(`/gw/rounds/${encodeURIComponent(roundId)}`),
        readJson<Mapping>(`/gw/rounds/${encodeURIComponent(roundId)}/schedule-mapping`),
      ]);
      if (!latest()) return;
      setDetail(d); setMapping(m);
      setPreview(null);                          // any re-read discards a stale proposal
      setTaxDraft({});                           // …including unsaved taxonomy proposals
    } catch (e) {
      if (latest()) setErr(e instanceof ReadError ? e.message : "read failed");
    }
  }, [roundId]);

  useEffect(() => { void load(); }, [load]);

  /** Canonical slots joined to the server's display codes. Order = the SERVER's accepted order. */
  const rows = useMemo(() => {
    if (!detail?.slots) return [];
    const byId = new Map(detail.slots.map((s) => [s.slot_id, s]));
    const ordered = mapping?.positions?.length
      ? mapping.positions.map((p) => ({ slot: byId.get(p.slot_id), code: p.display_code }))
      // Legacy by absence (#292): no governed mapping -> no display code. We say so; we do not mint one.
      : detail.slots.map((s) => ({ slot: s, code: null as string | null }));
    const ids = preview ?? ordered.map((o) => o.slot?.slot_id).filter(Boolean) as string[];
    const codeOf = new Map(ordered.map((o) => [o.slot?.slot_id, o.code]));
    return ids.map((id) => ({ slot: byId.get(id), code: codeOf.get(id) ?? null }))
              .filter((r): r is { slot: Slot; code: string | null } => !!r.slot);
  }, [detail, mapping, preview]);

  const shown = useMemo(() => rows.filter((r) => {
    const needle = q.trim().toLowerCase();
    if (needle && !`${r.code ?? ""} ${r.slot.slot_id} ${r.slot.format ?? ""}`.toLowerCase().includes(needle)) return false;
    if (status && (r.slot.status ?? "") !== status) return false;
    return true;
  }), [rows, q, status]);

  const statuses = useMemo(
    () => [...new Set(rows.map((r) => r.slot.status).filter(Boolean) as string[])].sort(),
    [rows],
  );

  /** Move a slot in the PREVIEW only. Nothing is committed until Apply. */
  const move = (id: string, delta: number) => {
    const base = preview ?? rows.map((r) => r.slot.slot_id);
    const i = base.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= base.length) return;
    const next = [...base];
    [next[i], next[j]] = [next[j], next[i]];
    setPreview(next);
    setFb({ kind: "idle" });
  };

  const commitOrder = async () => {
    if (!preview || !mapping) return;
    setFb({ kind: "busy", msg: "Applying order…" });
    try {
      const res = await fetch(`/gw/rounds/${encodeURIComponent(roundId)}/schedule-reorder`, {
        method: "POST", headers: { "content-type": "application/json" },
        // Canonical IDs + the accepted token. No actor: identity is signed server-side.
        body: JSON.stringify({ order: preview, schedule_token: mapping.schedule_token }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409) {
        setPreview(null);                        // visible revert to authoritative order
        await load();                            // …and re-read what was actually accepted
        setFb({ kind: "conflict", msg: `The schedule changed while you were reordering (your version ${mapping.schedule_token}, current ${body?.detail?.current_token ?? body?.current_token ?? "?"}). The accepted order is shown again — decide against it.` });
        return;
      }
      if (!res.ok) {
        setPreview(null); await load();
        setFb({ kind: "error", msg: typeof body?.detail === "string" ? body.detail : `reorder refused (${res.status})` });
        return;
      }
      await load();
      setFb({ kind: "ok", msg: "Order accepted." });
    } catch {
      setPreview(null); await load();
      setFb({ kind: "error", msg: "tanaghom api unreachable" });
    }
  };

  const reviseSlot = async (slotId: string, changes: Record<string, string | number>) => {
    if (!mapping) return;
    setFb({ kind: "busy", msg: `Revising ${slotId}…` });
    try {
      const res = await fetch(`/gw/slots/${encodeURIComponent(slotId)}/schedule-revision`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ changes, schedule_token: mapping.schedule_token }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409) {
        await load();
        setFb({ kind: "conflict", msg: `The schedule changed while you were revising (current ${body?.detail?.current_token ?? body?.current_token ?? "?"}). Refreshed — decide again.` });
        return;
      }
      if (!res.ok) {
        // Includes the governed refusals verbatim: not a revisable field, ineligible format under
        // the run's PINNED policy, slot past Schedule. Surfaced, not reworded into a guess.
        await load();
        setFb({ kind: "error", msg: typeof body?.detail === "string" ? body.detail : `revision refused (${res.status})` });
        return;
      }
      await load();
      setFb({ kind: "ok", msg: `${slotId} revised.` });
    } catch {
      await load();
      setFb({ kind: "error", msg: "tanaghom api unreachable" });
    }
  };

  if (err) {
    return (
      <div data-testid="run-schedule-error" className="rounded-xl border p-3 text-xs">
        <p>{err}</p>
        <button type="button" data-testid="run-schedule-retry" onClick={() => void load()}
                className="mt-2 rounded-md border px-2 py-1">Retry</button>
      </div>
    );
  }
  if (!detail || !mapping) return <div data-testid="run-schedule-loading" className="p-3 text-xs">Loading schedule…</div>;
  if (!rows.length) return <div data-testid="run-schedule-empty" className="rounded-xl border p-3 text-xs">This run has no planned cells.</div>;

  // Names only: the governed contract validates the framework by NAME. Display labels/tags are not
  // domain identity (#304), so nothing here treats the label as the identifier.
  const tax = detail.pinned_taxonomy;
  const eligible = (detail.pinned_eligible_formats ?? []).map((f) =>
    typeof f === "string" ? f : f?.name).filter(Boolean) as string[];

  return (
    <section data-testid="run-schedule-workspace" data-round-id={roundId} data-view={effectiveView.view}
             data-lens={lens} data-range-start={effectiveView.rangeStart ?? ""} data-range-end={effectiveView.rangeEnd ?? ""}
             className="flex flex-col gap-3">
      {/* #308 — the selected-run view system: adaptive Day/Week/Month/List/Custom-range over the run
          window, projecting canonical slots. Presentation only; the governed edits stay in the list.
          #382 — the lens SELECTOR moved to the shell's top lens menu (the single navigation authority);
          this workspace renders the projection for the resolved lens. `data-slot-order` is still
          emitted by EVERY lens from the same `shown` array, so a divergent copy or an independent sort
          stays detectable (#376 VIEW-01 parity, preserved). */}
      {lens === "calendar" && (
        <>
          <ScheduleViewToolbar scope={scope} state={effectiveView} onChange={setViewState} />
          <div data-testid="run-lens-calendar-panel" data-lens="calendar"
               data-slot-order={shown.map((r) => r.slot.slot_id).join(",")}>
            <RunScheduleCalendar
              startsOn={detail.starts_on}
              periodLenDays={detail.period_len_days}
              cells={shown.map((r) => ({ slot_id: r.slot.slot_id, code: r.code, day: r.slot.day, time_uae: r.slot.time_uae, status: r.slot.status }))}
              viewState={effectiveView}
            />
          </div>
        </>
      )}

      {lens === "grid" && (
        <ul data-testid="run-lens-grid-panel" data-lens="grid"
            data-slot-order={shown.map((r) => r.slot.slot_id).join(",")}
            className="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-2">
          {shown.map((r, idx) => (
            <li key={r.slot.slot_id} data-testid={`grid-cell-${r.slot.slot_id}`}
                data-slot-id={r.slot.slot_id} data-order-index={idx}
                className="flex flex-col gap-1 rounded-md border p-2 text-xs">
              <span className="font-mono font-medium">{r.code ?? "no governed code"}</span>
              <span className="font-mono opacity-60">{r.slot.slot_id}</span>
              <span>{r.slot.status ?? "—"}</span>
              <span className="text-(--color-muted)">
                day {r.slot.day ?? "—"}{r.slot.time_uae ? ` · ${String(r.slot.time_uae).slice(0, 5)}` : ""}
              </span>
              <span className="text-(--color-muted)">{r.slot.format ?? "—"}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Sticky selected-run scope controls (A15), wrapping so 375px never scrolls the page. */}
      <div data-testid="schedule-scope-controls" className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b bg-(--color-bg) p-2 text-xs">
        <label className="sr-only" htmlFor="schedule-search">Search cells</label>
        <input id="schedule-search" data-testid="schedule-search" type="search" placeholder="Search cells…"
               value={q} onChange={(e) => setQ(e.target.value)} className="min-w-0 flex-1 rounded-md border px-2 py-1" />
        <label className="sr-only" htmlFor="schedule-status">Filter by status</label>
        <select id="schedule-status" data-testid="schedule-status" value={status}
                onChange={(e) => setStatus(e.target.value)} className="rounded-md border px-2 py-1">
          <option value="">All statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span data-testid="schedule-scope-count" data-shown={shown.length} data-total={rows.length}>
          {shown.length} of {rows.length}{rows.length - shown.length > 0 ? ` · ${rows.length - shown.length} hidden by filters` : ""}
        </span>
      </div>

      <div ref={fbRef} tabIndex={-1} data-testid="run-schedule-feedback" data-kind={fb.kind} role="status" aria-live="polite" className="min-h-[1.25rem] text-xs outline-none">
        {fb.kind !== "idle" ? fb.msg : null}
        {(fb.kind === "error" || fb.kind === "conflict") && (
          <button type="button" data-testid="run-schedule-refresh" onClick={() => { setFb({ kind: "idle" }); void load(); }}
                  className="ml-2 rounded-md border px-2 py-0.5">Refresh</button>
        )}
      </div>

      {preview && (
        <div data-testid="order-preview" className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-xs">
          <span>Unsaved order — not applied until you commit.</span>
          <button type="button" data-testid="order-apply" onClick={() => void commitOrder()} className="rounded-md border px-2 py-1">Apply order</button>
          <button type="button" data-testid="order-discard" onClick={() => { setPreview(null); setFb({ kind: "idle" }); }} className="rounded-md border px-2 py-1">Discard</button>
        </div>
      )}

      {lens === "list" && (
      <>
      {/* #385 scope 1 — the reorder affordance is now DISCOVERABLE without trial-and-error: a visible
          guidance line states that dragging previews an order and Apply order commits it, and that the
          ↑/↓ buttons are the equal keyboard path. */}
      <p data-testid="reorder-guidance" className="rounded-md border border-(--color-border-subtle) bg-(--color-bg) p-2 text-[11px] text-(--color-muted)">
        Reorder cells by dragging a row by its <span aria-hidden className="font-mono">⠿</span> handle — this
        previews a new order and saves nothing until you choose <span className="font-medium text-(--color-fg)">Apply order</span>.
        The <span aria-hidden>↑ / ↓</span> buttons do exactly the same from the keyboard.
      </p>
      <ul data-testid="schedule-cells" data-lens="list"
          data-slot-order={shown.map((r) => r.slot.slot_id).join(",")}
          data-order-state={preview ? "preview" : "accepted"}
          className="flex flex-col gap-2">
        {shown.map((r, idx) => {
          // #385 scope 1 — with a single cell there is nothing to reorder; the handle reflects that
          // truthfully (a distinct disabled/frozen state) rather than inviting a drag that can't happen.
          const reorderable = shown.length > 1;
          const dragging = dragId === r.slot.slot_id;
          const dropTarget = !!dragId && dragId !== r.slot.slot_id && dropTargetId === r.slot.slot_id;
          return (
          <li key={r.slot.slot_id} data-testid={`cell-${r.slot.slot_id}`} data-slot-id={r.slot.slot_id}
              data-order-state={preview ? "preview" : "accepted"}
              data-reorderable={reorderable ? "true" : "false"}
              data-dragging={dragging ? "true" : undefined}
              data-drop-target={dropTarget ? "true" : undefined}
              draggable={reorderable}
              onDragStart={(e) => { e.dataTransfer.setData("text/plain", r.slot.slot_id); e.dataTransfer.effectAllowed = "move"; setDragId(r.slot.slot_id); }}
              onDragEnd={() => { setDragId(null); setDropTargetId(null); }}
              onDragOver={(e) => e.preventDefault()}
              onDragEnter={() => { if (dragId) setDropTargetId(r.slot.slot_id); }}
              onDrop={(e) => {
                e.preventDefault();
                const dragged = e.dataTransfer.getData("text/plain");
                setDragId(null); setDropTargetId(null);
                const base = preview ?? rows.map((x) => x.slot.slot_id);
                const from = base.indexOf(dragged), to = base.indexOf(r.slot.slot_id);
                if (from < 0 || to < 0 || from === to) return;
                const next = [...base];
                next.splice(to, 0, ...next.splice(from, 1));
                setPreview(next); setFb({ kind: "idle" });
              }}
              className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border p-2 text-xs ${
                dragging ? "border-dashed border-(--color-fg) opacity-60" : "border-(--color-border)"
              } ${dropTarget ? "ring-2 ring-(--color-fg)" : ""} ${preview ? "bg-(--color-bg)" : ""}`}>

            {/* ORDERING group — a VISIBLE drag handle plus the first-class keyboard controls, grouped
                so the "how do I reorder" affordances read as one unit (scope 6). */}
            <div data-group="ordering" className="flex items-center gap-1">
              <span data-testid={`cell-drag-${r.slot.slot_id}`} aria-hidden
                    title={reorderable ? "Drag to preview a new order — Apply order to save" : "Only one cell — nothing to reorder"}
                    className={`select-none rounded px-1 text-sm text-(--color-muted) ${reorderable ? "cursor-grab" : "cursor-not-allowed opacity-40"}`}>⠿</span>
              <button type="button" data-testid={`cell-up-${r.slot.slot_id}`} aria-label={`Move ${r.code ?? r.slot.slot_id} earlier`}
                      disabled={idx === 0} onClick={() => move(r.slot.slot_id, -1)} className="rounded-md border px-2 py-1 disabled:opacity-50">↑</button>
              <button type="button" data-testid={`cell-down-${r.slot.slot_id}`} aria-label={`Move ${r.code ?? r.slot.slot_id} later`}
                      disabled={idx === shown.length - 1} onClick={() => move(r.slot.slot_id, 1)} className="rounded-md border px-2 py-1 disabled:opacity-50">↓</button>
            </div>

            {/* IDENTITY + STATUS group */}
            <div data-group="identity" className="flex min-w-0 flex-wrap items-center gap-2">
              {/* display_code is the ROUTINE identifier … */}
              <span data-testid={`cell-code-${r.slot.slot_id}`} className="font-mono font-medium">
                {r.code ?? "no governed code"}
              </span>
              {/* … slot_id stays visible as SECONDARY diagnostic identity. */}
              <span data-testid={`cell-canonical-${r.slot.slot_id}`} className="font-mono opacity-60" title="canonical slot id (diagnostic)">
                {r.slot.slot_id}
              </span>
              <span data-testid={`cell-status-${r.slot.slot_id}`} className="rounded-full border border-(--color-border-subtle) px-1.5 py-0.5 text-(--color-muted)">{r.slot.status ?? "—"}</span>
            </div>

            {/* TIMING group */}
            <div data-group="timing" className="flex items-center gap-2 border-s border-(--color-border-subtle) ps-3">
              <label className="sr-only" htmlFor={`cell-day-${r.slot.slot_id}`}>Day for {r.code ?? r.slot.slot_id}</label>
              <input id={`cell-day-${r.slot.slot_id}`} data-testid={`cell-day-${r.slot.slot_id}`} type="number" min={1}
                     max={detail.period_len_days ?? undefined} defaultValue={r.slot.day ?? undefined}
                     className="w-16 rounded-md border px-1 py-0.5" />
              <label className="sr-only" htmlFor={`cell-time-${r.slot.slot_id}`}>Time for {r.code ?? r.slot.slot_id}</label>
              <input id={`cell-time-${r.slot.slot_id}`} data-testid={`cell-time-${r.slot.slot_id}`} type="time"
                     defaultValue={(r.slot.time_uae ?? "").slice(0, 5)} className="rounded-md border px-1 py-0.5" />
            </div>

            {/* CLASSIFICATION group */}
            <div data-group="classification" className="flex flex-wrap items-center gap-2 border-s border-(--color-border-subtle) ps-3">
              <label className="sr-only" htmlFor={`cell-format-${r.slot.slot_id}`}>Framework for {r.code ?? r.slot.slot_id}</label>
              {/* Options come from the run's PINNED policy generation — not the live catalogue. A later
                  policy change must never reinterpret this run. */}
              <select id={`cell-format-${r.slot.slot_id}`} data-testid={`cell-format-${r.slot.slot_id}`}
                      defaultValue={r.slot.format ?? ""} className="rounded-md border px-1 py-0.5">
                {eligible.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>

              {/* #306 — dependent Pillar -> HCS, resolved from the run's PINNED generation. */}
              {tax && tax.pillars.length > 0 && (() => {
                const draft = taxDraft[r.slot.slot_id];
                const pillar = draft?.pillar ?? r.slot.pillar_code ?? "";
                const hcsOptions = tax.hcs.filter((h) => h.pillar_code === pillar);
                const hcs = draft?.hcs ?? r.slot.hcs_id ?? "";
                const changed = !!draft && (draft.pillar !== (r.slot.pillar_code ?? "") || draft.hcs !== (r.slot.hcs_id ?? ""));
                return (
                  <>
                    <label className="sr-only" htmlFor={`cell-pillar-${r.slot.slot_id}`}>Pillar for {r.code ?? r.slot.slot_id}</label>
                    <select id={`cell-pillar-${r.slot.slot_id}`} data-testid={`cell-pillar-${r.slot.slot_id}`}
                            value={pillar}
                            onChange={(e) => {
                              // Changing the pillar invalidates the HCS: pick the first HCS the PINNED
                              // generation puts under the new pillar rather than keeping a combination
                              // the server would refuse.
                              const first = tax.hcs.find((h) => h.pillar_code === e.target.value);
                              setTaxDraft((d) => ({ ...d, [r.slot.slot_id]: { pillar: e.target.value, hcs: first?.hcs_id ?? "" } }));
                            }}
                            className="rounded-md border px-1 py-0.5">
                      {tax.pillars.map((p) => <option key={p.pillar_code} value={p.pillar_code}>{p.code_short || p.pillar_code}</option>)}
                    </select>
                    <label className="sr-only" htmlFor={`cell-hcs-${r.slot.slot_id}`}>HCS for {r.code ?? r.slot.slot_id}</label>
                    <select id={`cell-hcs-${r.slot.slot_id}`} data-testid={`cell-hcs-${r.slot.slot_id}`}
                            value={hcs}
                            onChange={(e) => setTaxDraft((d) => ({ ...d, [r.slot.slot_id]: { pillar, hcs: e.target.value } }))}
                            className="rounded-md border px-1 py-0.5">
                      {hcsOptions.map((h) => <option key={h.hcs_id} value={h.hcs_id}>{h.hcs_id}</option>)}
                    </select>
                    {/* Category is a PROJECTION of the chosen HCS, never an editable identity. */}
                    <span data-testid={`cell-category-${r.slot.slot_id}`} className="opacity-60" title="derived from the HCS — not an editable identity">
                      {tax.hcs.find((h) => h.hcs_id === hcs)?.name_en ?? "—"}
                    </span>
                    {changed && (
                      // Truthful consequence preview: state what an ACCEPTED commit would do, and what
                      // it would not. The code is regenerated by the SERVER, so we never show a guess.
                      // #385 scope 7 — absent optional classification renders "—", never literal "undefined".
                      <span data-testid={`tax-preview-${r.slot.slot_id}`} className="w-full text-[11px]">
                        Unsaved: {r.slot.pillar_code ?? "—"}/{r.slot.hcs_id ?? "—"} → {draft!.pillar}/{draft!.hcs}. On commit the
                        server re-resolves the lens, mints a new schedule generation and regenerates this
                        cell’s display code. Canonical id {r.slot.slot_id} and history do not change.
                      </span>
                    )}
                  </>
                );
              })()}
            </div>

            {/* EDIT group */}
            <div data-group="edit" className="flex items-center border-s border-(--color-border-subtle) ps-3">
              <button type="button" data-testid={`cell-revise-${r.slot.slot_id}`}
                      onClick={() => {
                        const day = Number((document.getElementById(`cell-day-${r.slot.slot_id}`) as HTMLInputElement)?.value);
                        const time = (document.getElementById(`cell-time-${r.slot.slot_id}`) as HTMLInputElement)?.value;
                        const fmt = (document.getElementById(`cell-format-${r.slot.slot_id}`) as HTMLSelectElement)?.value;
                        const changes: Record<string, string | number> = {};
                        if (day && day !== r.slot.day) changes.day = day;
                        if (time && time !== (r.slot.time_uae ?? "").slice(0, 5)) changes.time_uae = time;
                        if (fmt && fmt !== r.slot.format) changes.format = fmt;
                        // #306 — pillar+hcs travel together as an ATOMIC PAIR, exactly as the server
                        // requires: sending one alone is refused, and rightly so.
                        const d = taxDraft[r.slot.slot_id];
                        if (d && (d.pillar !== (r.slot.pillar_code ?? "") || d.hcs !== (r.slot.hcs_id ?? ""))) {
                          changes.pillar_code = d.pillar;
                          changes.hcs_id = d.hcs;
                        }
                        if (!Object.keys(changes).length) { setFb({ kind: "error", msg: "Nothing changed." }); return; }
                        void reviseSlot(r.slot.slot_id, changes);
                      }}
                      className="rounded-md border px-2 py-1">Revise</button>
            </div>
          </li>
          );
        })}
      </ul>
      </>
      )}

      {/* The governed per-slot edits and the reorder live in the List lens only — one owner, so no
          second surface can propose a write the list does not own. Said plainly rather than leaving
          an operator to wonder where the controls went. */}
      {lens !== "list" && (
        <p data-testid="run-lens-edit-hint" className="text-xs text-(--color-muted)">
          Switch to the List lens to revise or reorder cells — the governed edits live there.
        </p>
      )}
    </section>
  );
}
