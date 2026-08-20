"use client";

// #331 — the Topics stage workspace: the canonical COVERAGE ALLOCATIONS, useful BEFORE any topic copy
// exists, plus the governed manual Generate action and the reused generation/governance surfaces.
//
// SCOPE DISCIPLINE:
//   - The allocation set is ASSEMBLED from three existing unguarded reads and interprets nothing:
//       /rounds/{id}            -> canonical slots (day, time, format, pillar, hcs, status)
//       /rounds/{id}/schedule-mapping -> the client-facing display_code (schedule code) + token
//       /rounds/{id}/generation -> per-slot generation/topic STATE, entry_mode, phase, provisioning
//     Every field is server truth shown verbatim. Absent values are disclosed, never fabricated.
//   - TARGET PLATFORM has NO coverage read-model field (verified against SlotDetail / round_detail): it
//     is rendered truthfully UNAVAILABLE, never guessed. This is honest disclosure (accept #6), not a
//     missing feature — the directive pre-classified it.
//   - GENERATE is the CANONICAL #332 manual-start path through V2's /gw seam — never a second command.
//     It appears ONLY when the typed read model says it is available (manual entry mode, provisioned,
//     awaiting the trigger); automatic runs show observe-only truth with no button; busy/denied/
//     conflict/lifecycle are distinct states relayed verbatim.
//   - The generation OUTPUT detail (jobs, generated topics, provenance, per-item #313 governance) and
//     the #314 bulk/presentation governance are the EXISTING surfaces, reused as-is below — no second
//     path, no duplicated authority.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  readJson, ReadError,
  type RoundDetail, type SlotDetail, type TopicGenerationReadModel, type GenerationResult,
} from "@/lib/read-model";
import { GenerationSeam } from "./generation-seam";
import { BulkDisposition } from "./bulk-disposition";
import { TopicPresentationReorder } from "./topic-presentation-reorder";
import type { LensKey } from "@/lib/shell-lens";

type Mapping = { schedule_token: number; legacy: boolean; positions: { slot_id: string; display_code: string; display_position: number }[] };

/** One coverage allocation — a canonical slot joined to its schedule code and generation state. */
type Allocation = {
  slot_id: string;
  code: string | null;              // display_code = client-facing schedule code; null = legacy by absence
  day?: number;
  time_uae?: string | null;
  placement: string | null;         // absolute date from starts_on+(day-1), or null = unplaced
  format?: string | null;           // framework / content format
  pillar_code?: string | null;
  hcs_id?: string | null;
  slot_status?: string | null;
  generated: boolean;               // a topic exists for this slot
  inAcceptedSet: boolean;           // the slot is in the stage2A accepted/generation set
  langAr: boolean;                  // language availability (Arabic source) — only meaningful once content exists
  topic_id?: string | null;
  revision?: number | null;
};

/** starts_on + (day-1) as an ISO date, or null when the run is unplaced. Projection only — the server
 *  owns the placement; V2 never substitutes created_at or "today" (accept #6). */
function placementOf(startsOn: string | null | undefined, day?: number): string | null {
  if (!startsOn) return null;
  const base = new Date(`${startsOn}T00:00:00Z`);
  if (Number.isNaN(base.getTime())) return null;
  base.setUTCDate(base.getUTCDate() + (day && day > 0 ? day - 1 : 0));
  return base.toISOString().slice(0, 10);
}

const GEN_STATE_LABEL: Record<string, string> = {
  empty: "No generation yet",
  awaiting_trigger: "Awaiting manual trigger",
  queued: "Queued",
  running: "Generating…",
  partial: "Partially generated",
  failed: "Generation failed",
  completed: "Generated",
};

type GenFeedback = { kind: "idle" | "busy" | "ok" | "error" | "conflict"; msg?: string };

export function TopicsWorkspace({ roundId, lens }: { roundId: string; lens: LensKey }) {
  const [detail, setDetail] = useState<RoundDetail | null>(null);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [gen, setGen] = useState<TopicGenerationReadModel | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [genFb, setGenFb] = useState<GenFeedback>({ kind: "idle" });
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const latest = () => mine === seq.current;   // #286 — only the newest read may commit
    setErr(null);
    try {
      const [d, m, g] = await Promise.all([
        readJson<RoundDetail>(`/gw/rounds/${encodeURIComponent(roundId)}`),
        readJson<Mapping>(`/gw/rounds/${encodeURIComponent(roundId)}/schedule-mapping`),
        readJson<TopicGenerationReadModel>(`/gw/rounds/${encodeURIComponent(roundId)}/generation`),
      ]);
      if (!latest()) return;
      setDetail(d); setMapping(m); setGen(g);
    } catch (e) {
      if (latest()) setErr(e instanceof ReadError ? e.message : "read failed");
    }
  }, [roundId]);

  useEffect(() => { void load(); }, [load]);

  const allocations = useMemo<Allocation[]>(() => {
    if (!detail?.slots) return [];
    const codeOf = new Map((mapping?.positions ?? []).map((p) => [p.slot_id, p.display_code]));
    const resultOf = new Map<string, GenerationResult>((gen?.results ?? []).map((r) => [r.slot_id, r]));
    // Order by the accepted schedule mapping when present, else the server's slot order (never sorted here).
    const ordered: SlotDetail[] = mapping?.positions?.length
      ? mapping.positions.map((p) => detail.slots.find((s) => s.slot_id === p.slot_id)).filter(Boolean) as SlotDetail[]
      : detail.slots;
    return ordered.map((s) => {
      const res = resultOf.get(s.slot_id);
      const generated = !!res?.topic;
      return {
        slot_id: s.slot_id,
        code: codeOf.get(s.slot_id) ?? null,
        day: s.day,
        time_uae: s.time_uae,
        placement: placementOf(detail.starts_on, s.day),
        format: s.format,
        pillar_code: s.pillar_code,
        hcs_id: s.hcs_id,
        slot_status: res?.slot_status ?? s.status,
        generated,
        inAcceptedSet: !!res,
        langAr: generated,   // topics are Arabic-source; language availability follows content existence
        topic_id: res?.topic?.topic_id ?? null,
        revision: res?.topic?.revision ?? null,
      };
    });
  }, [detail, mapping, gen]);

  // ---- the CANONICAL manual Generate action (typed availability) ----
  const genModel = gen;
  const provisioned = !!genModel?.stage2a_enabled;
  const entryMode = genModel?.entry_mode ?? null;
  const phase = genModel?.phase ?? "";
  // Available strictly when the read model says so: provisioned + manual + awaiting the trigger. The
  // server is still the authority (it re-checks the immutable approver set); this only decides whether
  // to OFFER the action, never whether it will succeed.
  const generateAvailable = provisioned && entryMode === "manual" && phase === "awaiting_trigger";
  const isAutomatic = provisioned && entryMode === "automatic";
  const isBusy = provisioned && (phase === "queued" || phase === "running");

  const doGenerate = async () => {
    setGenFb({ kind: "busy", msg: "Starting Topic generation…" });
    let res: Response;
    try {
      // The canonical generation stage is `topic_review` (its writer_mode is `topics`), NOT the UI
      // stage-rail key "topics". This is the merged #332 manual-start route; V2 signs nothing itself.
      res = await fetch(`/gw/rounds/${encodeURIComponent(roundId)}/stages/topic_review/generate`, {
        method: "POST", headers: { "content-type": "application/json" }, body: "{}",
      });
    } catch {
      setGenFb({ kind: "error", msg: "tanaghom api unreachable" });
      return;
    }
    const body = await res.json().catch(() => ({} as Record<string, unknown>));
    const detailMsg = typeof body?.detail === "string" ? body.detail : null;
    if (res.ok) {
      // activated (started) or already (idempotent lifecycle replay) — both are truthful successes.
      const already = (body as { already?: boolean }).already;
      setGenFb({ kind: "ok", msg: already ? "Already started — generation is under way." : "Topic generation started." });
      await load();
      return;
    }
    if (res.status === 409) {
      // automatic-mode exclusion — a distinct state, not a failure the operator caused.
      setGenFb({ kind: "conflict", msg: detailMsg ?? "This run's Topic generation is automatic (triggered by governed Schedule acceptance)." });
      await load();
      return;
    }
    if (res.status === 403) {
      // coarse governed authorization-safe denial — relayed verbatim, target/mode never leaked.
      setGenFb({ kind: "error", msg: detailMsg ?? "Not authorized to start this run's Topic generation." });
      return;
    }
    setGenFb({ kind: "error", msg: detailMsg ?? `generation refused (${res.status})` });
  };

  if (err) {
    return (
      <div data-testid="topics-error" className="rounded-xl border p-3 text-xs">
        <p>{err}</p>
        <button type="button" data-testid="topics-retry" onClick={() => void load()} className="mt-2 rounded-md border px-2 py-1">Retry</button>
      </div>
    );
  }
  if (!detail || !mapping || !gen) return <div data-testid="topics-loading" className="p-3 text-xs">Loading Topics…</div>;

  return (
    <section data-testid="topics-workspace" data-round-id={roundId} data-lens={lens} className="flex flex-col gap-3">
      {/* ---- generate action strip (typed availability) ---- */}
      <div data-testid="topic-generate" data-phase={phase} data-entry-mode={entryMode ?? ""}
           data-available={generateAvailable ? "true" : "false"}
           className="flex flex-wrap items-center gap-2 rounded-xl border border-(--color-border) bg-(--color-card) p-3 text-xs">
        <span className="font-semibold">Topic generation</span>
        <span data-testid="topic-generate-state" className="rounded-full border px-2 py-0.5 text-[10px]">
          {/* #385 scope 7 — an absent/empty phase renders "—", never a blank chip or literal text. */}
          {GEN_STATE_LABEL[phase] ?? (phase || "—")}
        </span>
        {generateAvailable && (
          <button type="button" data-testid="topic-generate-action" disabled={genFb.kind === "busy"}
                  onClick={() => void doGenerate()}
                  className="rounded-md border border-(--color-border) px-3 py-1 font-medium hover:bg-(--color-bg) disabled:opacity-50">
            Generate topics
          </button>
        )}
        {isAutomatic && (
          <span data-testid="topic-generate-automatic" className="text-(--color-muted)">
            Automatic — generation is triggered by governed Schedule acceptance; there is no manual start here.
          </span>
        )}
        {isBusy && (
          <span data-testid="topic-generate-busy" className="text-(--color-muted)">Generation is under way — no manual start needed.</span>
        )}
        {!provisioned && (
          <span data-testid="topic-generate-unavailable" className="text-(--color-muted)">
            Topic generation is not provisioned for this run — no generation command is available.
          </span>
        )}
        <span data-testid="topic-generate-feedback" data-kind={genFb.kind} role="status" aria-live="polite"
              className={`w-full ${genFb.kind === "error" || genFb.kind === "conflict" ? "text-(--color-danger)" : "text-(--color-muted)"}`}>
          {genFb.kind !== "idle" ? genFb.msg : null}
        </span>
      </div>

      {/* ---- coverage allocations (lens-controlled presentation of the SAME set) ---- */}
      <CoverageAllocations lens={lens} allocations={allocations} />

      {/* ---- reused generation OUTPUT + per-item #313 governance (observe/act as before) ---- */}
      <GenerationSeam roundId={roundId} />

      {/* ---- reused #314 bulk disposition + presentation reorder, in the Topics context ---- */}
      <section data-testid="topics-governance" className="flex flex-col gap-3">
        {/* #385 scope 4 / acceptance 6 — prominent, persistent copy that separates the two axes an
            operator conflates here: EDITORIAL SEQUENCE (below) versus governed SCHEDULE TIMING (the
            Coverage / Calendar stage). It also states plainly why the Calendar view is not offered in
            Topics, so the disabled lens is explained at the point of confusion, not only in the menu. */}
        <div data-testid="topic-order-semantics" className="flex flex-col gap-1 rounded-md border border-(--color-border) bg-(--color-card) p-3 text-[11px] text-(--color-muted)">
          <p>
            <span className="font-semibold text-(--color-fg)">Presentation order is editorial only.</span> The
            Topic presentation order below changes the SEQUENCE topics are shown in — it never changes a run’s
            schedule, a cell’s timing, disposition, or content.
          </p>
          <p>
            <span className="font-semibold text-(--color-fg)">Run and cell timing is governed elsewhere.</span> Timing
            lives on the Coverage / Planning (Calendar) stage — which is why the Calendar view is not offered here in
            Topics. Switch to the Schedule stage to change timing.
          </p>
        </div>
        <BulkDisposition roundId={roundId} />
        <TopicPresentationReorder roundId={roundId} />
      </section>
    </section>
  );
}

/** The presentation of the allocation set. Same data; list / grid / overview change layout ONLY —
 *  never the underlying truth, and never fabricate a field. */
function CoverageAllocations({ lens, allocations }: { lens: LensKey; allocations: Allocation[] }) {
  if (allocations.length === 0) {
    return <div data-testid="coverage-allocations-empty" className="rounded-xl border p-3 text-xs">This run has no coverage allocations.</div>;
  }

  if (lens === "overview") {
    const total = allocations.length;
    const generated = allocations.filter((a) => a.generated).length;
    const placed = allocations.filter((a) => a.placement).length;
    const byFormat = allocations.reduce<Record<string, number>>((acc, a) => {
      const k = a.format ?? "—"; acc[k] = (acc[k] ?? 0) + 1; return acc;
    }, {});
    return (
      <div data-testid="coverage-allocations" data-lens="overview" className="flex flex-col gap-2 rounded-xl border border-(--color-border) bg-(--color-card) p-3 text-xs">
        <h3 className="text-sm font-semibold">Coverage overview</h3>
        <ul className="flex flex-wrap gap-x-6 gap-y-1">
          <li data-testid="coverage-count-total">Allocations: <b>{total}</b></li>
          <li data-testid="coverage-count-generated">Generated: <b>{generated}</b> / {total}</li>
          <li data-testid="coverage-count-placed">Placed: <b>{placed}</b> / {total}</li>
        </ul>
        <div>
          <p className="font-medium">By framework</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {Object.entries(byFormat).map(([f, n]) => (
              <li key={f} className="rounded-full border px-2 py-0.5">{f}: {n}</li>
            ))}
          </ul>
        </div>
        <p data-testid="coverage-platform-note" className="text-[11px] text-(--color-muted)">
          Target platform is not part of the coverage read model — it is shown as unavailable rather than guessed.
        </p>
      </div>
    );
  }

  const wrap = lens === "grid"
    ? "grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3"
    : "flex flex-col gap-2";

  return (
    <div data-testid="coverage-allocations" data-lens={lens} className="flex flex-col gap-2">
      <p data-testid="coverage-platform-note" className="text-[11px] text-(--color-muted)">
        Target platform is not part of the coverage read model — shown as unavailable rather than guessed.
      </p>
      <ul className={wrap} data-testid="coverage-allocation-list">
        {allocations.map((a, i) => {
          // #335 Editorial grouping — a PURE ordered projection: the group label is derived from the
          // already-ordered allocation's placement and rendered INSIDE its own <li> (never as a sibling
          // <li>, so the canonical allocation count is unchanged). It reorders nothing, changes no
          // input/identity/payload, and is shown only under the Editorial style (CSS-gated); List keeps
          // its natural order in both styles.
          const group = a.placement ?? "Unplaced";
          const startsGroup = lens === "list" && (i === 0 || (allocations[i - 1].placement ?? "Unplaced") !== group);
          return (
          <li key={a.slot_id} data-testid={`alloc-${a.slot_id}`} data-slot-id={a.slot_id}
              data-generated={a.generated ? "true" : "false"}
              className="flex flex-col gap-1 rounded-lg border border-(--color-border) bg-(--color-card) p-2 text-xs">
            {startsGroup && (
              <span data-testid={`alloc-group-${a.slot_id}`} data-group={group}>{group}</span>
            )}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {/* client-facing schedule code — the routine identifier */}
              <span data-testid={`alloc-code-${a.slot_id}`} className="font-mono font-medium">
                {a.code ?? "no governed code"}
              </span>
              {a.slot_status && (
                <span data-testid={`alloc-status-${a.slot_id}`} className="rounded-full border px-2 py-0.5 text-[10px]">{a.slot_status}</span>
              )}
              {/* generation + review state */}
              <span data-testid={`alloc-genstate-${a.slot_id}`} className="rounded-full border px-2 py-0.5 text-[10px]">
                {a.generated ? "Generated" : "Topic allocated; content not generated"}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-(--color-muted)">
              {/* placement — absolute date or explicit unplaced */}
              <span data-testid={`alloc-placement-${a.slot_id}`}>
                {a.placement
                  ? `${a.placement}${a.time_uae ? ` · ${a.time_uae.slice(0, 5)}` : ""}`
                  : "Unplaced — no governed start"}
              </span>
              {/* target platform — truthfully unavailable */}
              <span data-testid={`alloc-platform-${a.slot_id}`} data-available="false" title="not in the coverage read model">
                Platform: —
              </span>
              {/* framework / content format */}
              <span data-testid={`alloc-format-${a.slot_id}`}>{a.format ?? "no framework"}</span>
              {/* pillar / topic class */}
              <span data-testid={`alloc-class-${a.slot_id}`}>
                {[a.pillar_code, a.hcs_id].filter(Boolean).join(" · ") || "unclassified"}
              </span>
              {/* language availability — only meaningful once content exists */}
              <span data-testid={`alloc-lang-${a.slot_id}`}>
                {a.generated ? "AR" : "language: pending generation"}
              </span>
            </div>

            {/* diagnostic identity — slot/topic ids, secondary */}
            <details data-testid={`alloc-inspect-${a.slot_id}`} className="text-[10px] text-(--color-muted)">
              <summary className="cursor-pointer">Inspect</summary>
              <p className="mt-1 font-mono">slot {a.slot_id}{a.topic_id ? ` · topic ${a.topic_id} · rev ${a.revision}` : " · no topic yet"}</p>
            </details>
          </li>
          );
        })}
      </ul>
    </div>
  );
}
