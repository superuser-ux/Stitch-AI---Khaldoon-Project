"use client";

// #335/#380 — the Light / Dark appearance control (deterministic, explicit-selection only).
//
// #380 makes the workbench deterministically LIGHT-FIRST for UAT: the host OS preference never drives
// the theme, so the OS-following "System" option is removed and the two explicit selections are Light
// (default) and Dark. Modeled on the DirToggle discipline: it adopts the AUTHORITATIVE document state
// after hydration (the pre-paint initializer already reconciled <html> to the stored preference, so the
// DOM is the truth), exposes each option as a keyboard-operable button with a STABLE accessible name
// and an explicit aria-pressed state, and reflects a change by setting the <html> attribute +
// best-effort persistence. It is PRESENTATION-ONLY: it never issues a request and never touches any
// canonical value. Appearance stays orthogonal to direction (`dir`) and schedule style.

import { useCallback, useEffect, useState } from "react";
import {
  type Appearance, APPEARANCES, DEFAULT_APPEARANCE,
  applyAppearance, writeAppearance, currentAppearanceFromDom,
} from "@/lib/presentation-prefs";

const LABEL: Record<Appearance, string> = { light: "Light", dark: "Dark" };

export function AppearanceToggle() {
  // SSR/first-paint renders the default; after hydration we adopt what the document actually shows so
  // the control can never announce the wrong selection (the DirToggle no-drift rule).
  const [appearance, setAppearance] = useState<Appearance>(DEFAULT_APPEARANCE);

  useEffect(() => {
    setAppearance(currentAppearanceFromDom());
  }, []);

  const choose = useCallback((next: Appearance) => {
    applyAppearance(next);   // reflect on <html> (explicit light/dark sets data-theme; system removes it)
    writeAppearance(next);   // best-effort persist; a storage failure is swallowed, selection still applies
    setAppearance(next);
  }, []);

  return (
    <div
      data-testid="wb-appearance"
      role="group"
      aria-label="Appearance mode"
      className="inline-flex items-center gap-0.5 rounded-md border border-(--color-border) p-0.5"
    >
      {APPEARANCES.map((mode) => {
        const selected = appearance === mode;
        return (
          <button
            key={mode}
            type="button"
            data-testid={`wb-appearance-${mode}`}
            aria-pressed={selected}
            aria-label={`${LABEL[mode]} appearance`}
            onClick={() => choose(mode)}
            className={`rounded-[0.35rem] px-2 py-0.5 text-[11px] font-medium ${
              selected ? "bg-(--color-accent) text-(--color-on-accent)" : "text-(--color-muted) hover:bg-(--color-bg)"
            }`}
          >
            {LABEL[mode]}
          </button>
        );
      })}
    </div>
  );
}
