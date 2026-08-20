"use client";

// #308 — the accessible view/range toolbar shared by both Schedule levels.
//
// Every view is a plain button and every control is keyboard reachable; on a compact/mobile toolbar
// the buttons wrap rather than crop, so no action is ever hidden and the page never scrolls sideways.
// Custom Range exposes two date inputs whose ONLY effect is the presentation window — they call the
// same `onChange` the view buttons do and touch no server state.

import { SCHEDULE_VIEWS, type ScheduleView, type ViewState } from "./schedule-views";

type Props = {
  scope: string;                     // "runs" or a round_id — for stable, non-colliding testids
  state: ViewState;
  onChange: (next: ViewState) => void;
};

export function ScheduleViewToolbar({ scope, state, onChange }: Props) {
  return (
    <div
      data-testid={`view-toolbar-${scope}`}
      role="toolbar"
      aria-label="Calendar display"
      className="flex flex-wrap items-center gap-1"
    >
      {/* #385 scope 3 — a visible hierarchy caption: this toolbar is the "Calendar display" (how the
          calendar lens presents), distinct from the top "Workspace view" lens. */}
      <span
        data-testid={`view-toolbar-label-${scope}`}
        className="me-1 text-[11px] font-medium uppercase tracking-wide text-(--color-muted)"
      >
        Calendar display
      </span>
      {SCHEDULE_VIEWS.map((v) => (
        <button
          key={v.key}
          type="button"
          data-testid={`view-${scope}-${v.key}`}
          aria-pressed={state.view === v.key}
          onClick={() => onChange({ ...state, view: v.key })}
          className={`rounded-md border px-2 py-1 text-xs ${state.view === v.key ? "bg-secondary font-medium" : ""}`}
        >
          {v.key === "range" ? "Custom range" : v.label}
        </button>
      ))}

      {state.view === "range" && (
        <span data-testid={`range-inputs-${scope}`} className="flex flex-wrap items-center gap-1">
          <label className="sr-only" htmlFor={`range-start-${scope}`}>Range start</label>
          <input
            id={`range-start-${scope}`}
            data-testid={`range-start-${scope}`}
            type="date"
            value={state.rangeStart ?? ""}
            onChange={(e) => onChange({ ...state, rangeStart: e.target.value })}
            className="rounded-md border px-1 py-0.5 text-xs"
          />
          <span aria-hidden>–</span>
          <label className="sr-only" htmlFor={`range-end-${scope}`}>Range end</label>
          <input
            id={`range-end-${scope}`}
            data-testid={`range-end-${scope}`}
            type="date"
            value={state.rangeEnd ?? ""}
            onChange={(e) => onChange({ ...state, rangeEnd: e.target.value })}
            className="rounded-md border px-1 py-0.5 text-xs"
          />
        </span>
      )}
    </div>
  );
}
