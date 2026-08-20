"use client";

// #308 Stage 1C — the shared FullCalendar Standard view system for both Schedule levels.
//
// Six views, ONE contract: Day, Week, Month, List, Adaptive Run Range, and a presentation-only
// Custom Range. All map onto v7 Standard MIT subpaths already authorized by #304 — day grid, time
// grid, list — with NO Premium/Scheduler/resource/timeline, AGPL, or commercial dependency.
//
// WHAT A VIEW IS, AND IS NOT (the whole point of this slice):
//   A view is a PROJECTION. Switching a view or a range changes what the operator SEES and nothing
//   else — never run placement, slot day/time, the display mapping, or historical evidence. #304's
//   read-boundary already proves V2 issues no upstream request on navigation, so a range change
//   CANNOT mutate data; there is no code path for it to. Custom Range is presentation-only by
//   construction, not by promise.
//
// ADAPTIVE IS DETERMINISTIC FROM SERVER TRUTH, never viewport guesswork: the initial selected-run
// view derives from `period_len_days`, and the exact window is the half-open `starts_on ..
// starts_on + period_len_days` #304 established.

import type { CalendarApi } from "@fullcalendar/react";
import classicThemePlugin from "@fullcalendar/react/themes/classic";

// #340 — the ONE FullCalendar theme both Schedule levels render with.
//
// A v7 theme is a PluginInput, not a prop: its stylesheet is scoped under a `.fc-classic` class that
// only appears when the plugin is registered, so importing the theme CSS without this is inert. It
// lives HERE, beside the shared view contract, so the two calendar surfaces cannot drift onto
// different themes — the directive's "no divergent per-surface CSS mechanisms".
//
// Only the THEME is shared. Each surface still composes its own view plugins, because their
// capabilities are deliberately different: the run-index registers `interaction` (placement is
// proposed there) and the selected-run calendar does not. Sharing the plugin ARRAY would quietly
// hand drag authority to a surface that must not have it.
export const SCHEDULE_THEME_PLUGIN = classicThemePlugin;

/** The stable view keys. `range` is the adaptive/custom presentation window; the rest are v7 views. */
export type ScheduleView = "day" | "week" | "month" | "list" | "range";

export const SCHEDULE_VIEWS: { key: ScheduleView; label: string; fcView: string }[] = [
  { key: "day", label: "Day", fcView: "timeGridDay" },
  { key: "week", label: "Week", fcView: "timeGridWeek" },
  { key: "month", label: "Month", fcView: "dayGridMonth" },
  // #385 scope 3 — this internal calendar presentation is labelled "Agenda", not "List", so it no
  // longer collides with the top workspace "List" lens. The stable KEY stays `list` (URL `v_{scope}=list`
  // and every deep link keep their governed meaning); only the visible label changed.
  { key: "list", label: "Agenda", fcView: "listWeek" },
  { key: "range", label: "Range", fcView: "dayGrid" }, // arbitrary day span; duration set at runtime
];

const FC_VIEW = new Map(SCHEDULE_VIEWS.map((v) => [v.key, v.fcView]));
export function fcViewFor(view: ScheduleView): string {
  return FC_VIEW.get(view) ?? "dayGridMonth";
}

/** The half-open run window as #304 defines it: [starts_on, starts_on + period_len_days). Returns
 *  null for an unplaced run — the caller renders that explicitly, never a fabricated date. */
export function runWindow(startsOn: string | null | undefined, periodLenDays: number | null | undefined):
  { start: string; endExclusive: string; days: number } | null {
  if (!startsOn) return null;
  const days = periodLenDays && periodLenDays > 0 ? periodLenDays : 1;
  const start = new Date(`${startsOn}T00:00:00Z`);
  const end = new Date(start);
  end.setUTCDate(end.getUTCDate() + days);          // exclusive — FullCalendar end is exclusive
  return { start: startsOn, endExclusive: end.toISOString().slice(0, 10), days };
}

/** #308 — the DETERMINISTIC adaptive initial view for a selected run, from server truth only:
 *    1-day     -> day
 *    2..7-day  -> exact run-duration multi-day view (a bounded range)
 *    longer    -> month grid (day-grid/range), with list/month controls available
 *    unplaced  -> list (there is no window to project; the workspace states "unplaced" separately)
 *  The viewport is never consulted. */
export function adaptiveView(startsOn: string | null | undefined, periodLenDays: number | null | undefined): ScheduleView {
  const w = runWindow(startsOn, periodLenDays);
  if (!w) return "list";
  if (w.days <= 1) return "day";
  if (w.days <= 7) return "range";
  return "month";
}

/** #308 — a per-scope view/range state that round-trips through the URL so it is shareable and
 *  restorable across drill-down/back/reload. `scope` keys it (e.g. "runs" or a round_id) so context
 *  NEVER leaks across unrelated runs: reading another scope's params returns that scope's state only. */
export type ViewState = { view: ScheduleView; rangeStart?: string; rangeEnd?: string };

export function readViewState(params: URLSearchParams, scope: string, fallback: ScheduleView): ViewState {
  const raw = params.get(`v_${scope}`);
  const view = (SCHEDULE_VIEWS.some((v) => v.key === raw) ? raw : fallback) as ScheduleView;
  const rangeStart = params.get(`rs_${scope}`) || undefined;
  const rangeEnd = params.get(`re_${scope}`) || undefined;
  return { view, rangeStart, rangeEnd };
}

/** Write this scope's state into a copy of the given params, leaving every OTHER scope's keys intact
 *  — so switching a run's view cannot disturb the runs-calendar's, or another run's. */
export function writeViewState(params: URLSearchParams, scope: string, state: ViewState): URLSearchParams {
  const next = new URLSearchParams(params.toString());
  next.set(`v_${scope}`, state.view);
  if (state.view === "range" && state.rangeStart && state.rangeEnd) {
    next.set(`rs_${scope}`, state.rangeStart);
    next.set(`re_${scope}`, state.rangeEnd);
  } else {
    next.delete(`rs_${scope}`);
    next.delete(`re_${scope}`);
  }
  return next;
}

/** Apply a view/range to a live FullCalendar without remounting it. Range navigation is a pure
 *  presentation call (`changeView` / `gotoDate`) — it issues no upstream request. */
export function applyView(api: CalendarApi, state: ViewState): void {
  if (state.view === "range" && state.rangeStart && state.rangeEnd) {
    const days = Math.max(
      1,
      Math.round(
        (new Date(`${state.rangeEnd}T00:00:00Z`).getTime() - new Date(`${state.rangeStart}T00:00:00Z`).getTime())
          / 86_400_000,
      ) + 1,
    );
    api.changeView("dayGrid", { start: state.rangeStart, end: state.rangeEnd });
    void days;
    api.gotoDate(state.rangeStart);
    return;
  }
  api.changeView(fcViewFor(state.view));
}
