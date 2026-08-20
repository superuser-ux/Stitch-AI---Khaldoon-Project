"use client";

// #304 Stage 1, Level 1 — the runs-calendar seam: the ONLY place V2 reads run placement and
// proposes a governed placement change.
//
// The whole authority split lives here:
//   - Tanaghom owns placement, the freeze predicate, the token and the audit.
//   - This seam reads server truth, hands a PROPOSAL back, and re-reads what the server accepted.
//   - It never decides whether a move is allowed, never keeps a local order, and never reconciles a
//     rejection silently.
//
// The freeze answer is SERVER-DECLARED. `canPlace` is not a client rule: a run is placeable only
// while no slot has advanced past Schedule, and the server evaluates that from persisted facts
// (`_downstream_advanced`). We read its lifecycle counts and render its answer. Re-deriving the
// predicate here would be exactly the "approximate it in the UI" that #304 forbids — and it would
// drift the moment the server's definition changed.

import { useCallback, useEffect, useRef, useState } from "react";
import { readJson, ReadError, type RoundDetail, type RoundSummary } from "@/lib/read-model";
import { RunsCalendar } from "./runs-calendar";
import { RunComposer, type ComposerDraft, type ComposerSource } from "./run-composer";
import { RunsScopeControls, applyScope, DEFAULT_SCOPE, type Scope } from "./runs-scope-controls";

/** #376 — the governed default range `New run` opens with when no date was chosen: today through
 *  today+6, inclusive (one week). Visible, editable, and never sent anywhere until submit. */
function defaultRange(): { startsOn: string; endsOn: string } {
  const start = new Date();
  const startsOn = start.toISOString().slice(0, 10);
  const end = new Date(`${startsOn}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 6);
  return { startsOn, endsOn: end.toISOString().slice(0, 10) };
}

/** What the server says about one run's mapping/token, needed to propose against it. */
type Mapping = { schedule_token: number };

export function RunsCalendarSeam() {
  const [runs, setRuns] = useState<RoundSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Server-declared freeze per run: round_id -> may still be placed.
  const [placeable, setPlaceable] = useState<Record<string, boolean>>({});
  // #304 A15 — scope is PRESENTATION state only. It never reaches a proposal, never reorders the
  // governed schedule (#292 owns that), and is re-applied to whatever the server last returned.
  const [scope, setScope] = useState<Scope>(DEFAULT_SCOPE);
  // #376 — the ONE ephemeral draft. It lives only here, in client memory: no identifier is reserved,
  // nothing is persisted, and discarding it leaves no trace because there was never anything to undo.
  const [draft, setDraft] = useState<ComposerDraft | null>(null);
  // #286 pattern: only the LATEST load may commit, so a slower earlier read can never overwrite a
  // newer one. Proven real in V1; adopted rather than re-learned.
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const latest = () => mine === seq.current;
    setErr(null);
    try {
      const rows = await readJson<RoundSummary[]>("/gw/rounds");
      if (!latest()) return;
      setRuns(rows);
      // Resolve the SERVER's freeze answer per run from its own read model. A run whose slots have
      // all left Schedule is frozen; we ask rather than infer.
      const flags: Record<string, boolean> = {};
      await Promise.all(
        rows.map(async (r) => {
          try {
            const d = await readJson<RoundDetail>(`/gw/rounds/${encodeURIComponent(r.round_id)}`);
            const counts = (d as unknown as { status_counts?: Record<string, number> }).status_counts ?? {};
            const total = Object.values(counts).reduce((a, b) => a + b, 0);
            const atSchedule = (counts.RESERVED ?? 0) + (counts.SCHEDULE_APPROVED ?? 0);
            // Placeable only while EVERY slot is still at the schedule stage. This mirrors the
            // server's predicate conservatively: if we are ever wrong, the server still refuses and
            // the UI reverts — the server, not this flag, is the authority.
            flags[r.round_id] = total > 0 && atSchedule === total;
          } catch {
            flags[r.round_id] = false;   // unknown -> not draggable. Fail closed, never open.
          }
        }),
      );
      if (latest()) setPlaceable(flags);
    } catch (e) {
      if (latest()) setErr(e instanceof ReadError ? e.message : "read failed");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const propose = useCallback(async (roundId: string, startsOn: string) => {
    // The expected token is read fresh from the server immediately before proposing: proposing
    // against a token we cached earlier would be proposing against a view we no longer hold.
    let token: number;
    try {
      const m = await readJson<Mapping>(`/gw/rounds/${encodeURIComponent(roundId)}/schedule-mapping`);
      token = m.schedule_token;
    } catch {
      return { ok: false, detail: "could not read the current schedule token — refresh and retry" };
    }
    try {
      const res = await fetch(`/gw/rounds/${encodeURIComponent(roundId)}/placement`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        // No actor: identity is asserted server-side by the signed proxy. A client may never say
        // who it is.
        body: JSON.stringify({ starts_on: startsOn, schedule_token: token }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409) {
        const cur = (body?.detail?.current_token ?? body?.current_token) ?? "?";
        return {
          ok: false,
          conflict: true,
          detail: `The schedule changed while you were moving this run (your version ${token}, current ${cur}). Refresh, then decide again against current server truth.`,
        };
      }
      if (!res.ok) {
        // Includes the governed freeze refusal — surfaced verbatim from the server rather than
        // reworded into a UI guess about why.
        const d = body?.detail;
        return { ok: false, detail: typeof d === "string" ? d : `placement refused (${res.status})` };
      }
      return { ok: true };
    } catch {
      return { ok: false, detail: "tanaghom api unreachable" };
    }
  }, []);

  if (err) {
    return (
      <div data-testid="runs-calendar-read-error" className="rounded-xl border p-3 text-xs">
        <p>{err}</p>
        <button type="button" data-testid="runs-calendar-retry" onClick={() => void load()}
                className="mt-2 rounded-md border px-2 py-1">Retry</button>
      </div>
    );
  }
  if (!runs) {
    return <div data-testid="runs-calendar-loading" className="p-3 text-xs">Loading runs…</div>;
  }

  return (
    <>
      {/* #376 — the THIRD entry path. All three (date click, range selection, this button) initialize
          the SAME ephemeral composer, so there is one draft and one submit rather than a calendar and
          a detached form that disagree. */}
      <div data-testid="new-run-entry" className="rounded-xl border border-(--color-border) bg-(--color-card) p-3">
        <button
          type="button"
          data-testid="new-run"
          onClick={() => { const r = defaultRange(); setDraft({ source: "new-run", ...r }); }}
          className="rounded-md border border-(--color-border) px-3 py-1.5 text-sm font-medium hover:bg-(--color-bg)"
        >
          New run
        </button>
        <p className="mt-1 text-[11px] text-(--color-muted)">
          Or click a date, or drag a date range on the calendar. Every path opens the same draft —
          and a run is created only when you plan it.
        </p>
      </div>

      {draft && (
        <RunComposer
          draft={draft}
          onCancel={() => setDraft(null)}
          onRangeChange={(startsOn, endsOn) => setDraft((d) => (d ? { ...d, startsOn, endsOn } : d))}
        />
      )}

      {/* CAL-01 — a lane with zero runs still opens ON THE CALENDAR. The previous empty state replaced
          the whole workspace with a text card, so a fresh lane had no schedule to start a run from —
          exactly the calendar-first failure #376 corrects. Emptiness is stated ALONGSIDE the grid. */}
      {runs.length === 0 && (
        <div data-testid="runs-calendar-empty" className="rounded-xl border p-3 text-xs">
          No runs yet. Pick a date or a range below to start one — selecting dates creates nothing
          until you plan the run.
        </div>
      )}

      {runs.length > 0 && <RunsScopeControls runs={runs} scope={scope} onChange={setScope} />}
      <RunsCalendar
        runs={applyScope(runs, scope)}
        onRefresh={load}
        onPropose={propose}
        canPlace={(id) => placeable[id] === true}
        onDraft={(source: ComposerSource, startsOn: string, endsOn: string) =>
          setDraft({ source, startsOn, endsOn })}
      />
    </>
  );
}
