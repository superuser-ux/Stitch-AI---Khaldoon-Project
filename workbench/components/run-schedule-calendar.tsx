"use client";

// #308 Stage 1C, Level 2 — the selected-run calendar PROJECTION.
//
// This renders the run's complete canonical slot population as FullCalendar events, positioned from
// the run's AUTHORITATIVE start and each slot's RELATIVE day/time — a slot's datetime is
// `starts_on + (day-1)` at `time_uae` (#304). It is a projection only: event identity is the
// canonical `slot_id`, the routine label is the server `display_code`, and switching view/range
// changes nothing on the server (FullCalendar navigation issues no upstream request). The governed
// day/time/format/taxonomy/reorder writes live in the sibling list workspace, unchanged; drag here
// is deliberately not added, so this surface can never propose a write the list does not own.
//
// UNPLACED: a run with no `starts_on` has no window to project. We say so explicitly rather than
// inventing a date — the same "unplaced is truth" rule #304 established for Level 1.

import { useEffect, useMemo, useRef } from "react";
import FullCalendar, { type CalendarRef } from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import timeGridPlugin from "@fullcalendar/react/timegrid";
import listPlugin from "@fullcalendar/react/list";
import { applyView, fcViewFor, runWindow, SCHEDULE_THEME_PLUGIN, type ViewState } from "./schedule-views";

type Cell = { slot_id: string; code: string | null; day?: number; time_uae?: string | null; status?: string | null };

type Props = {
  startsOn: string | null | undefined;
  periodLenDays: number | null | undefined;
  cells: Cell[];
  viewState: ViewState;
};

/** Absolute datetime of a slot from the run's start + relative day/time. Read-only derivation. */
function slotDateTime(startsOn: string, day: number | undefined, timeUae: string | null | undefined): string {
  const base = new Date(`${startsOn}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() + Math.max(0, (day ?? 1) - 1));
  const dateStr = base.toISOString().slice(0, 10);
  const t = (timeUae ?? "").trim();
  return t ? `${dateStr}T${t.length === 5 ? t : t.slice(0, 5)}:00` : dateStr;
}

export function RunScheduleCalendar({ startsOn, periodLenDays, cells, viewState }: Props) {
  const win = runWindow(startsOn, periodLenDays);

  const events = useMemo(() => {
    if (!startsOn) return [];
    return cells.map((c) => ({
      id: c.slot_id,
      title: c.code || c.slot_id,     // display_code is the routine identifier; slot_id is the fallback
      start: slotDateTime(startsOn, c.day, c.time_uae),
      allDay: !((c.time_uae ?? "").trim()),
      extendedProps: { slotId: c.slot_id, status: c.status ?? "" },
    }));
  }, [startsOn, cells]);

  const calRef = useRef<CalendarRef | null>(null);
  useEffect(() => {
    const api = calRef.current?.getApi?.();
    if (!api) return;
    applyView(api, viewState);
    // Anchor the view on the run's own window, not "today", so a placed run always opens on itself.
    if (win) api.gotoDate(win.start);
  }, [viewState.view, viewState.rangeStart, viewState.rangeEnd, win?.start]);

  if (!startsOn) {
    return (
      <div data-testid="run-schedule-calendar-unplaced" className="rounded-xl border p-3 text-xs">
        This run has no governed start yet — its schedule cannot be placed on a calendar. Use the list
        below to review and revise its cells; place the run from the runs calendar to see it here.
      </div>
    );
  }

  return (
    <div data-testid="run-schedule-calendar" data-view={viewState.view} className="w-full max-w-full overflow-x-auto">
      <FullCalendar
        ref={calRef}
        plugins={[dayGridPlugin, timeGridPlugin, listPlugin, SCHEDULE_THEME_PLUGIN]}
        initialView={fcViewFor(viewState.view)}
        initialDate={win?.start}
        headerToolbar={{ left: "prev,next today", center: "title", right: "" }}
        height="auto"
        events={events}
        editable={false}
        eventContent={(arg) => (
          <span
            data-testid={`cal-slot-${arg.event.extendedProps.slotId}`}
            data-slot-id={arg.event.extendedProps.slotId}
            className="block truncate px-1 py-0.5 text-xs font-mono"
            title={String(arg.event.extendedProps.slotId)}
          >
            {arg.event.title}
          </span>
        )}
      />
    </div>
  );
}
