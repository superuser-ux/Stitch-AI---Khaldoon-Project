"use client";

import { useCallback, useEffect, useState } from "react";

// #315 ruling 3 — the shared text-direction toggle. It is rendered wherever a reviewer works with
// bilingual content (the home shell AND the run-scoped Topic surface), so RTL is a real, reachable
// affordance rather than a chrome-only control the review surfaces can't exercise.
//
// RTL safety is proven by flipping the REAL document direction — the same signal the browser's bidi
// algorithm uses — so CSS logical properties (ms-/me-/ps-/pe-/text-start) are exercised for real
// rather than simulated by a class. `dir` is authoritative on <html>, so that is the node we set.
//
// The toggle flips ONLY `dir`. The document chrome stays lang="en": the UI chrome is English, and
// relabeling <html lang="ar"> under RTL would tell assistive tech the entire English UI is Arabic.
// Language is declared truthfully PER NODE on the content via the bilingual presentation utility.
//
// #315 review finding 5 — the control must never DRIFT from the authoritative document direction. It
// adopts `document.documentElement.dir` after hydration (so client back/forward navigation, or another
// mounted toggle that already flipped the document, cannot leave this button announcing the wrong
// state and needing two clicks to correct). State is exposed as an explicit `aria-pressed` toggle with
// a STABLE accessible name ("Right-to-left text direction") — the name does not change with state; the
// pressed value carries the state — so AT users get a consistent, unambiguous control.

type Dir = "ltr" | "rtl";

const readDocDir = (): Dir => (document.documentElement.getAttribute("dir") === "rtl" ? "rtl" : "ltr");

export function DirToggle() {
  const [dir, setDir] = useState<Dir>("ltr");

  // Adopt the authoritative document direction after hydration — the button reflects reality, not a
  // hardcoded LTR assumption.
  useEffect(() => {
    setDir(readDocDir());
  }, []);

  const toggleDir = useCallback(() => {
    // Derive from the LIVE document, not just local state, so we can never invert a direction another
    // toggle/navigation already set.
    const next: Dir = readDocDir() === "ltr" ? "rtl" : "ltr";
    document.documentElement.setAttribute("dir", next);
    setDir(next);
  }, []);

  const pressed = dir === "rtl";
  return (
    <button
      type="button"
      data-testid="wb-dir-toggle"
      onClick={toggleDir}
      aria-pressed={pressed}
      aria-label="Right-to-left text direction"
      className="rounded-md border border-(--color-border) px-2 py-1 text-xs font-medium hover:bg-(--color-bg)"
    >
      {pressed ? "RTL" : "LTR"}
    </button>
  );
}
