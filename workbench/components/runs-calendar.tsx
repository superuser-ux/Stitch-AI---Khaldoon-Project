"use client";

// #304 Stage 1, Level 1 — the runs calendar.
//
// A RUN is the schedulable container/event here, distinct from its content slots. What this
// component may and may not do is the whole point of the slice:
//
//   MAY: project server truth onto a calendar, and turn a gesture into a PROPOSAL.
//   MAY NOT: own placement, order, lifecycle, or identity. There is no local shadow model.
//
// The gesture contract (#304):
//     calendar gesture
//       -> Tanaghom proposal (canonical round_id + expected combined schedule_token)
//       -> server validates principal, lifecycle freeze, pinned policy, membership, concurrency
//       -> accepted server state is RE-READ
//       -> rejection/409 reverts visibly and demands explicit refresh
//
// FullCalendar is presentation and gesture only. It never decides whether a move is allowed: the
// server's `_downstream_advanced` predicate does, and we render its answer.
//
// UNPLACED IS TRUTH, NOT AN ERROR: a run with `starts_on == null` was never governed-placed (legacy,
// or created through V1's placement-less form). #304 forbids deriving a window from `created_at`, so
// such runs are listed explicitly as unplaced and are NOT drawn on the grid. Hiding them, or drawing
// them at a guessed date, would both be lies.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import FullCalendar, { type CalendarRef } from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import timeGridPlugin from "@fullcalendar/react/timegrid";
import listPlugin from "@fullcalendar/react/list";
import interactionPlugin from "@fullcalendar/react/interaction";
import type { RoundSummary } from "@/lib/read-model";
import { applyView, fcViewFor, readViewState, writeViewState, SCHEDULE_THEME_PLUGIN, type ViewState } from "./schedule-views";
import { ScheduleViewToolbar } from "./schedule-view-toolbar";

type Props = {
  runs: RoundSummary[];
  /** Re-read of server truth. Called after every accepted commit and every explicit refresh. */
  onRefresh: () => void | Promise<void>;
  /** Commits a placement proposal upstream. Resolves to the typed server outcome. */
  onPropose: (roundId: string, startsOn: string) => Promise<{ ok: boolean; detail?: string; conflict?: boolean }>;
  /** Server-declared freeze: true when the run may still be placed. Never computed here. */
  canPlace: (roundId: string) => boolean;
  /** #376 — initializes the ONE ephemeral composer from a calendar gesture. Purely client-side: this
   *  callback issues no request and creates nothing durable. Dates are INCLUSIVE. */
  onDraft: (source: "date-click" | "range", startsOn: string, endsOn: string) => void;
};

/** FullCalendar reports an all-day selection with an EXCLUSIVE end (`2026-08-01..2026-08-04` means
 *  three days). The composer, the preview and the planner all speak INCLUSIVE dates, so the
 *  conversion happens once, here, at the boundary — never in three places that could disagree. */
function inclusiveEnd(endExclusive: string): string {
  const d = new Date(`${endExclusive}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

/** The run's window as SERVER data allows it to be drawn. Returns null when unplaced — the caller
 *  must render that truthfully rather than substituting any other date. */
function windowOf(r: RoundSummary): { start: string; end: string } | null {
  if (!r.starts_on) return null;
  const days = r.period_len_days && r.period_len_days > 0 ? r.period_len_days : 1;
  const start = new Date(`${r.starts_on}T00:00:00Z`);
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + days);          // FullCalendar end is exclusive
  return { start: r.starts_on, end: end.toISOString().slice(0, 10) };
}

export function RunsCalendar({ runs, onRefresh, onPropose, canPlace, onDraft }: Props) {
  const [status, setStatus] = useState<
    { kind: "idle" | "busy" | "ok" | "error" | "conflict"; msg?: string }
  >({ kind: "idle" });

  // #308 — the runs-calendar's view/range is scoped "runs" in the URL, so it is shareable/restorable
  // and cannot collide with any selected-run's state. Month is the portfolio default.
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const viewState = readViewState(new URLSearchParams(params?.toString() ?? ""), "runs", "month");
  const setViewState = useCallback((next: ViewState) => {
    const qs = writeViewState(new URLSearchParams(params?.toString() ?? ""), "runs", next);
    router.replace(`${pathname}?${qs.toString()}`, { scroll: false });
  }, [params, router, pathname]);

  const calRef = useRef<CalendarRef | null>(null);
  // Drive the live calendar from the URL state — presentation only, no upstream request.
  useEffect(() => {
    const api = calRef.current?.getApi?.();
    if (api) applyView(api, viewState);
  }, [viewState.view, viewState.rangeStart, viewState.rangeEnd]);

  const placed = useMemo(() => runs.filter((r) => !!r.starts_on), [runs]);
  const unplaced = useMemo(() => runs.filter((r) => !r.starts_on), [runs]);

  // #342 — which run the single placement control is pointed at. PRESENTATION ONLY: it is never
  // sent to the server, never persisted, and confers no placement authority.
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  // Default to the first run once truth arrives, and recover if the selected run disappears from
  // server truth (deleted, or filtered out) — a stale id would silently point the editor at nothing.
  useEffect(() => {
    if (!runs.length) { if (selectedRunId) setSelectedRunId(""); return; }
    if (!runs.some((r) => r.round_id === selectedRunId)) setSelectedRunId(runs[0].round_id);
  }, [runs, selectedRunId]);

  const selectedRun = useMemo(
    () => runs.find((r) => r.round_id === selectedRunId) ?? null,
    [runs, selectedRunId],
  );
  // Client-derived indication only — see the note on the frozen hint below. Never authoritative.
  const placeableNow = !!selectedRunId && canPlace(selectedRunId);

  const events = useMemo(
    () =>
      placed.flatMap((r) => {
        const w = windowOf(r);
        if (!w) return [];
        return [{
          id: r.round_id,
          title: r.label || r.round_id,
          start: w.start,
          end: w.end,
          allDay: true,
          // The server's freeze answer decides draggability. FullCalendar is told; it never decides.
          editable: canPlace(r.round_id),
          extendedProps: { roundId: r.round_id, slots: r.slots ?? 0 },
        }];
      }),
    [placed, canPlace],
  );

  const commit = useCallback(
    async (roundId: string, startsOn: string, revert: () => void) => {
      setStatus({ kind: "busy", msg: `Proposing ${roundId} → ${startsOn}…` });
      const res = await onPropose(roundId, startsOn);
      if (res.ok) {
        // Re-read server truth rather than trusting the local move: the accepted state is the
        // server's, and it may differ from what was dragged.
        await onRefresh();
        setStatus({ kind: "ok", msg: `${roundId} placed on ${startsOn}.` });
        return;
      }
      // Rejection/409: the optimistic gesture is a lie until the server accepts it, so it is undone
      // VISIBLY and the operator is told to refresh — never silently reconciled.
      revert();
      setStatus({
        kind: res.conflict ? "conflict" : "error",
        msg: res.detail || (res.conflict ? "Another change was accepted first." : "Placement refused."),
      });
    },
    [onPropose, onRefresh],
  );

  return (
    <section data-testid="runs-calendar" aria-label="Runs calendar" className="flex flex-col gap-3">
      <div
        data-testid="runs-calendar-status"
        data-kind={status.kind}
        role="status"
        aria-live="polite"
        className="min-h-[1.5rem] text-sm"
      >
        {status.kind !== "idle" ? status.msg : null}
        {(status.kind === "error" || status.kind === "conflict") && (
          <button
            type="button"
            data-testid="runs-calendar-refresh"
            onClick={() => { setStatus({ kind: "idle" }); void onRefresh(); }}
            className="ml-2 rounded-md border px-2 py-0.5 text-xs"
          >
            Refresh
          </button>
        )}
      </div>

      <ScheduleViewToolbar scope="runs" state={viewState} onChange={setViewState} />

      {/* #385 scope 2 — a compact, always-visible legend that distinguishes the three separate calendar
          gestures. Previously the only cue that a run could (or could not) be moved was FullCalendar's
          drag behaviour plus a native `title`; the legend + the per-event movable/frozen marker below
          make each gesture discoverable without hovering or trial-and-error. */}
      <div data-testid="calendar-legend" className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-(--color-border-subtle) bg-(--color-bg) p-2 text-[11px] text-(--color-muted)">
        <span className="font-medium text-(--color-fg)">Calendar gestures</span>
        <span data-testid="calendar-legend-create" className="flex items-center gap-1">
          <span aria-hidden className="inline-block size-3 rounded-sm border border-dashed border-(--color-fg)" />
          Click a date or drag across empty dates → start a new-run draft (nothing is created until you plan it)
        </span>
        <span data-testid="calendar-legend-move" className="flex items-center gap-1">
          <span aria-hidden className="font-mono">⠿</span>
          Drag a movable run → propose a new governed start
        </span>
        <span data-testid="calendar-legend-frozen" className="flex items-center gap-1">
          <span aria-hidden>🔒</span>
          A frozen run can’t be moved here
        </span>
      </div>

      {/* The grid scrolls inside its own container so the PAGE never scrolls horizontally at 375px. */}
      <div data-testid="runs-calendar-grid" data-view={viewState.view} className="w-full max-w-full overflow-x-auto">
        <FullCalendar
          ref={calRef}
          plugins={[dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin, SCHEDULE_THEME_PLUGIN]}
          initialView={fcViewFor(viewState.view)}
          headerToolbar={{ left: "prev,next today", center: "title", right: "" }}
          height="auto"
          events={events}
          editable
          eventStartEditable
          eventDurationEditable={false}
          // Custom Tanaghom rendering — the adapter renders OUR card, not vendor chrome.
          // #385 scope 2 — a VISIBLE movable/frozen affordance (⠿ vs 🔒) on every event, plus a
          // screen-reader phrase, so the server's freeze answer is legible without relying on `title`
          // or on discovering that a drag silently does nothing. `data-movable` mirrors `editable`.
          eventContent={(arg) => {
            const roundId = String(arg.event.extendedProps.roundId);
            const movable = canPlace(roundId);
            return (
              <Link
                href={`/runs/${encodeURIComponent(roundId)}`}
                data-testid={`run-event-${roundId}`}
                data-round-id={roundId}
                data-movable={movable ? "true" : "false"}
                className="flex items-center gap-1 truncate px-1 py-0.5 text-xs underline"
                title={arg.event.title}
              >
                <span aria-hidden className="no-underline">{movable ? "⠿" : "🔒"}</span>
                <span className="truncate">{arg.event.title}</span>
                <span className="sr-only">{movable ? " (movable — drag to propose a new start)" : " (frozen — cannot be moved here)"}</span>
              </Link>
            );
          }}
          eventDrop={(info) => {
            const roundId = info.event.extendedProps.roundId as string;
            const startsOn = info.event.startStr.slice(0, 10);
            void commit(roundId, startsOn, () => info.revert());
          }}
          // #376 — the two calendar entry paths into the composer. Both are PURE CLIENT GESTURES:
          // they call back with dates and do nothing else. No request is issued here, so a click or a
          // drag-select cannot create a run, reserve an identifier, or write an audit row — the
          // "clicking dates never creates durable state" rule is structural, not a promise.
          selectable
          unselectAuto={false}
          select={(info) => {
            onDraft("range", info.startStr.slice(0, 10), inclusiveEnd(info.endStr.slice(0, 10)));
          }}
          dateClick={(info) => {
            const day = info.dateStr.slice(0, 10);
            onDraft("date-click", day, day);      // a single clicked date is a ONE-DAY inclusive range
          }}
        />
      </div>

      {/* #304 A6 / #342 — the NON-DRAG path. Drag is additive; it is never the only way to place a
          run. This is the same governed proposal the gesture makes (canonical id + expected token,
          server decides, accepted state re-read, refusal surfaced) — reached entirely by keyboard,
          and the only path available to anyone who cannot drag. Not a "fallback" behind a
          preference: a first-class control.

          #342 — ONE control, bound to a chosen run, replacing the previous editor-per-run list.
          That list rendered a date input and a Move button for EVERY run, so a lane with 102 runs
          produced 102 unrelated placement editors — unusable, and it buried the one run the
          operator actually meant. A compact selection surface is the shape the directive names, and
          it is keyboard-native: `<select>` needs no custom key handling, roving tabindex, or ARIA
          widget role to be operable, so there is less to get wrong than a bespoke listbox.

          The selection is PRESENTATION ONLY. It creates no client-owned placement authority, is
          never sent to the server, and survives nothing — it only decides which run this one editor
          is currently pointed at. */}
      <div data-testid="placement-controls" className="rounded-md border p-2">
        <h3 className="text-xs font-medium">Move a run (no drag required)</h3>
        <div className="mt-1 flex flex-wrap items-end gap-2 text-xs">
          <span className="flex flex-col gap-1">
            <label htmlFor="placement-run">Run</label>
            <select
              id="placement-run"
              data-testid="placement-run-select"
              value={selectedRunId}
              onChange={(e) => setSelectedRunId(e.target.value)}
              className="rounded-md border px-2 py-1"
            >
              {runs.map((r) => (
                <option key={r.round_id} value={r.round_id}>
                  {r.label || r.round_id}
                </option>
              ))}
            </select>
          </span>

          <span className="flex flex-col gap-1">
            <label htmlFor="placement-date">Scheduled start</label>
            <input
              id="placement-date"
              data-testid="placement-date"
              type="date"
              // Re-keyed on the selection so the field always shows the SERVER's current start for
              // the run in view, never a value left over from the previously selected run.
              key={selectedRunId}
              defaultValue={selectedRun?.starts_on ?? ""}
              disabled={!placeableNow}
              className="rounded-md border px-2 py-1"
            />
          </span>

          <button
            type="button"
            data-testid="placement-submit"
            disabled={!placeableNow}
            aria-describedby={placeableNow ? undefined : "placement-frozen-hint"}
            onClick={() => {
              const el = document.getElementById("placement-date") as HTMLInputElement | null;
              const v = el?.value;
              if (!v || !selectedRunId) return;
              // Nothing moved optimistically, so there is no revert to undo: the proposal is either
              // accepted (and we re-read the accepted state) or refused (and we say so verbatim).
              void commit(selectedRunId, v, () => {});
            }}
            className="rounded-md border px-2 py-1 disabled:opacity-50"
          >
            Move
          </button>
        </div>

        {/* #342 — this hint is an INDICATION, not a verdict. The enabled/disabled state is derived
            in the client from lifecycle counts and is NOT the server's freeze predicate, which also
            accounts for downstream artifacts and post-schedule gate decisions the client cannot
            see. Wording it as a statement of fact ("Frozen — execution has begun") would claim an
            authority this surface does not have. The server decides on submit, and its typed
            refusal is surfaced verbatim in the status region above. Correcting the underlying
            divergence is deliberately out of #342's scope. */}
        {!placeableNow && selectedRunId && (
          <p id="placement-frozen-hint" data-testid="placement-frozen-hint" className="mt-1 text-xs text-(--color-muted)">
            This run looks frozen (execution may have begun), so the control is disabled here. The
            server makes the final decision and will state its reason if a move is refused.
          </p>
        )}
      </div>

      {/* Unplaced runs are stated, never hidden and never drawn at a guessed date. */}
      <div data-testid="unplaced-runs" aria-label="Unplaced runs" className="rounded-md border p-2">
        <h3 className="text-xs font-medium">Not scheduled ({unplaced.length})</h3>
        {unplaced.length === 0 ? (
          <p data-testid="unplaced-empty" className="text-xs text-(--color-muted)">
            Every run has a governed start.
          </p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1">
            {unplaced.map((r) => (
              <li key={r.round_id} data-testid={`unplaced-run-${r.round_id}`} className="text-xs">
                <Link href={`/runs/${encodeURIComponent(r.round_id)}`} className="underline">
                  {r.label || r.round_id}
                </Link>{" "}— no scheduled start yet
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
