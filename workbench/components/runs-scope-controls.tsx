"use client";

// #304 A15 — sticky scope controls: run search, filter, status and sort.
//
// THE ONE RULE THIS FILE EXISTS TO HONOUR (#304): "These controls must remain server-truth
// projections. Search/filter/sort presentation may not create a second lifecycle, ordering or policy
// model."
//
// So:
//   - every option is DERIVED from the rows the server returned — no hardcoded status vocabulary,
//     because inventing one would silently assert a lifecycle the server may not have;
//   - sorting reorders PRESENTATION only. It is not the governed schedule order (#292 owns that,
//     persisted/versioned/audited) and it never proposes anything;
//   - filtering hides rows from view. It never implies a run stopped existing, and the counts state
//     what is hidden so a filtered view can't be mistaken for the whole truth.

import { useMemo } from "react";
import type { RoundSummary } from "@/lib/read-model";

export type Scope = {
  q: string;
  status: string;      // "" = all. Values come from server rows, never a local vocabulary.
  placement: "all" | "placed" | "unplaced";
  sort: "start-asc" | "start-desc" | "id-asc";
};

export const DEFAULT_SCOPE: Scope = { q: "", status: "", placement: "all", sort: "start-asc" };

/** Status values the SERVER actually reported. Absence of a status here means the server did not
 *  report it — not that it cannot exist. */
export function statusesOf(runs: RoundSummary[]): string[] {
  const s = new Set<string>();
  for (const r of runs) {
    const phase = (r as unknown as { phase?: string | null }).phase;
    if (phase) s.add(phase);
  }
  return [...s].sort();
}

/** Presentation projection. Pure: same rows + same scope -> same output, and it never mutates. */
export function applyScope(runs: RoundSummary[], scope: Scope): RoundSummary[] {
  const q = scope.q.trim().toLowerCase();
  let out = runs.filter((r) => {
    if (q && !`${r.label ?? ""} ${r.round_id}`.toLowerCase().includes(q)) return false;
    if (scope.status) {
      const phase = (r as unknown as { phase?: string | null }).phase ?? "";
      if (phase !== scope.status) return false;
    }
    if (scope.placement === "placed" && !r.starts_on) return false;
    if (scope.placement === "unplaced" && r.starts_on) return false;
    return true;
  });
  out = [...out].sort((a, b) => {
    if (scope.sort === "id-asc") return a.round_id.localeCompare(b.round_id);
    // Unplaced runs have no start to sort by. They sort LAST rather than being given a fabricated
    // date — a sort must not invent the value it sorts on.
    const av = a.starts_on ?? "", bv = b.starts_on ?? "";
    if (!av && !bv) return a.round_id.localeCompare(b.round_id);
    if (!av) return 1;
    if (!bv) return -1;
    return scope.sort === "start-desc" ? bv.localeCompare(av) : av.localeCompare(bv);
  });
  return out;
}

export function RunsScopeControls({
  runs, scope, onChange,
}: { runs: RoundSummary[]; scope: Scope; onChange: (s: Scope) => void }) {
  const statuses = useMemo(() => statusesOf(runs), [runs]);
  const shown = useMemo(() => applyScope(runs, scope).length, [runs, scope]);
  const hidden = runs.length - shown;

  return (
    <div
      data-testid="runs-scope-controls"
      // Sticky at every width. It wraps rather than scrolling the page sideways — a control bar that
      // pushes the document horizontally is the exact 375px failure #304 names.
      className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b bg-(--color-bg) p-2 text-xs"
    >
      <label className="sr-only" htmlFor="runs-search">Search runs</label>
      <input
        id="runs-search"
        data-testid="runs-search"
        type="search"
        placeholder="Search runs…"
        value={scope.q}
        onChange={(e) => onChange({ ...scope, q: e.target.value })}
        className="min-w-0 flex-1 rounded-md border px-2 py-1"
      />

      <label className="sr-only" htmlFor="runs-status">Filter by status</label>
      <select
        id="runs-status"
        data-testid="runs-status"
        value={scope.status}
        onChange={(e) => onChange({ ...scope, status: e.target.value })}
        className="rounded-md border px-2 py-1"
      >
        <option value="">All statuses</option>
        {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      <label className="sr-only" htmlFor="runs-placement">Filter by placement</label>
      <select
        id="runs-placement"
        data-testid="runs-placement"
        value={scope.placement}
        onChange={(e) => onChange({ ...scope, placement: e.target.value as Scope["placement"] })}
        className="rounded-md border px-2 py-1"
      >
        <option value="all">All runs</option>
        <option value="placed">Scheduled</option>
        <option value="unplaced">Not scheduled</option>
      </select>

      <label className="sr-only" htmlFor="runs-sort">Sort runs</label>
      <select
        id="runs-sort"
        data-testid="runs-sort"
        value={scope.sort}
        onChange={(e) => onChange({ ...scope, sort: e.target.value as Scope["sort"] })}
        className="rounded-md border px-2 py-1"
      >
        <option value="start-asc">Start ↑</option>
        <option value="start-desc">Start ↓</option>
        <option value="id-asc">Run id</option>
      </select>

      {/* A filtered view must never read as the whole truth. */}
      <span data-testid="runs-scope-count" data-shown={shown} data-hidden={hidden}>
        {shown} of {runs.length}{hidden > 0 ? ` · ${hidden} hidden by filters` : ""}
      </span>
    </div>
  );
}
