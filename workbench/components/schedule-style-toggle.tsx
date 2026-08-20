"use client";

// #335 — the Editorial / Operational schedule-style control.
//
// PRESENTATION-ONLY, exactly like the appearance control: it sets `data-schedule-style` on <html> and
// best-effort persists the choice. It changes ONLY how the schedule/coverage surfaces are laid out
// (density, hierarchy, editorial date grouping) — it never reorders rows, changes date derivation,
// run/slot identity, schedule tokens, actions, permissions, filtering/grouping INPUTS, or any write
// payload. It adopts the authoritative document state after hydration (no drift), is keyboard-operable
// with stable accessible names + aria-pressed, and stays orthogonal to appearance and direction.

import { useCallback, useEffect, useState } from "react";
import {
  type ScheduleStyle, SCHEDULE_STYLES, DEFAULT_SCHEDULE_STYLE,
  applyScheduleStyle, writeScheduleStyle, currentScheduleStyleFromDom,
} from "@/lib/presentation-prefs";

const LABEL: Record<ScheduleStyle, string> = { editorial: "Editorial", operational: "Operational" };

export function ScheduleStyleToggle() {
  const [style, setStyle] = useState<ScheduleStyle>(DEFAULT_SCHEDULE_STYLE);

  useEffect(() => {
    setStyle(currentScheduleStyleFromDom());
  }, []);

  const choose = useCallback((next: ScheduleStyle) => {
    applyScheduleStyle(next);
    writeScheduleStyle(next);
    setStyle(next);
  }, []);

  return (
    <div
      data-testid="wb-schedule-style"
      role="group"
      aria-label="Schedule presentation style"
      className="inline-flex items-center gap-0.5 rounded-md border border-(--color-border) p-0.5"
    >
      {SCHEDULE_STYLES.map((s) => {
        const selected = style === s;
        return (
          <button
            key={s}
            type="button"
            data-testid={`wb-schedule-style-${s}`}
            aria-pressed={selected}
            aria-label={`${LABEL[s]} schedule style`}
            onClick={() => choose(s)}
            className={`rounded-[0.35rem] px-2 py-0.5 text-[11px] font-medium ${
              selected ? "bg-(--color-accent) text-(--color-on-accent)" : "text-(--color-muted) hover:bg-(--color-bg)"
            }`}
          >
            {LABEL[s]}
          </button>
        );
      })}
    </div>
  );
}
