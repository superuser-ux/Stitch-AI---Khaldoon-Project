"use client";

// #331/#382 — the run workspace: the persistent-context Level-2 surface reached by opening a run from
// the schedule-first root. It realises the context model `selected run → lifecycle STAGE → view LENS`.
//
//   - The SELECTED RUN is the route (`/runs/{id}`) — canonical server identity carried verbatim, never
//     parsed or reinterpreted. Persistent context: it stays across stage/lens changes and is reached by
//     navigation, never a hand-typed URL (accept #3).
//   - The STAGE (artifact domain) and LENS (presentation) are URL query state resolved by the ONE
//     shared shell-nav authority (#382 ruling 2), so a selection is visible, keyboard reachable,
//     link/reload-stable and reminds no identity. Unknown/disabled values are canonicalized by the
//     shell (never render a stale view).
//   - #382 — the stage rail and the lens menu now live in the CONTAINMENT SHELL (the sole navigation
//     owner, ruling 3). This workspace no longer renders a rail or lens chrome of its own; it consumes
//     the resolved stage/gate/lens from `useShellNav` and renders only the selected stage's PANEL into
//     the shell's single <main>. Panels are routed by the governed `gate_stage`, not the stage key —
//     the two may legitimately differ (#355).

import { useEffect, useState } from "react";
import Link from "next/link";
import { RunScheduleWorkspace } from "./run-schedule-workspace";
import { TopicsWorkspace } from "./topics-workspace";
import { ScriptsWorkspace } from "./scripts-workspace";
import { FinalReviewWorkspace } from "./final-review-workspace";
import { useShellNav } from "./shell-nav";
import { readJson, ReadError, type RoundDetail } from "@/lib/read-model";

export function RunWorkspace({ roundId }: { roundId: string }) {
  const { resolvedStage, gate, lens } = useShellNav();

  // #355 P1.3 — the canonical round read carries LOADING / ERROR / OK separately for the Scripts lens.
  // Collapsing a failed read into an empty slot list would make "the server did not answer" render as
  // "this run has no slots" — a fabricated empty success this lane exists to avoid.
  const [slots, setSlots] = useState<
    { phase: "loading" } | { phase: "ok"; ids: readonly string[] } | { phase: "error"; detail: string }
  >({ phase: "loading" });

  useEffect(() => {
    const ac = new AbortController();
    setSlots({ phase: "loading" });
    readJson<RoundDetail>(`/gw/rounds/${encodeURIComponent(roundId)}`, ac.signal)
      .then((r) => setSlots({ phase: "ok", ids: (r.slots ?? []).map((s) => s.slot_id) }))
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setSlots({ phase: "error", detail: e instanceof ReadError ? e.message : "the run could not be read" });
      });
    return () => ac.abort();
  }, [roundId]);

  return (
    <div
      data-testid="run-workspace"
      data-round-id={roundId}
      data-stage={resolvedStage?.key ?? ""}
      data-gate-stage={gate ?? ""}
      className="mx-auto flex max-w-5xl flex-col gap-3"
    >
      {/* persistent run context header */}
      <nav aria-label="Breadcrumb" data-testid="run-breadcrumb" className="text-xs">
        <Link href="/" data-testid="back-to-schedule" className="underline">Runs schedule</Link>
        <span aria-hidden className="mx-1">/</span>
        <span data-testid="run-crumb-current" className="font-mono">{roundId}</span>
      </nav>

      {/* selected stage workspace — routed by CANONICAL gate_stage. The rail (in the shell) shows the
          truthful unavailable state when the governed artifact cannot be read; here no panel renders. */}
      {gate === "schedule_review" && (
        <section data-testid="stage-panel-schedule_review" className="flex flex-col gap-2">
          <p className="text-[11px] text-(--color-muted)">
            Coverage / Planning uses the schedule view controls below (Day / Week / Month / List).
          </p>
          <RunScheduleWorkspace roundId={roundId} lens={lens} />
        </section>
      )}

      {gate === "topic_review" && (
        <section data-testid="stage-panel-topic_review" className="flex flex-col gap-2">
          <TopicsWorkspace roundId={roundId} lens={lens ?? "list"} />
        </section>
      )}

      {gate === "script_review" && (
        <section data-testid="stage-panel-script_review" className="flex flex-col gap-2">
          <ScriptsWorkspace roundId={roundId} gateStage={gate} slots={slots} />
        </section>
      )}

      {/* R1 Stage 4 — Final Review. Routed by the CANONICAL gate exactly like the panels above, so a
          governed version that renames the stage key still reaches the right surface, and a version
          that omits or disables the stage never resolves to this gate at all. The gate string is
          passed through verbatim rather than re-stated inside the panel: the panel addresses the
          server by the gate the artifact declared, not by a literal of its own. */}
      {gate === "final_review" && (
        <section data-testid="stage-panel-final_review" className="flex flex-col gap-2">
          <FinalReviewWorkspace roundId={roundId} gateStage={gate} />
        </section>
      )}
    </div>
  );
}
