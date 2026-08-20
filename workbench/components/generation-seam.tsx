"use client";

// #310 §F, Level 2 — the read-only Stage 2A Topic-generation seam for one run.
//
// SCOPE DISCIPLINE (why this file is careful):
//   - READ ONLY. V2 reads GET /rounds/{id}/generation through its own allowlisted seam and renders
//     server truth verbatim. It infers NO phase, derives NO counts, and completes NO field the
//     server left absent. `phase` and every status string are shown exactly as returned.
//   - PROVENANCE is DISCLOSURE, not decoration: resolved provider/model/route + novelty-brief
//     version + pinned generations are what ACTUALLY ran, shown as-is.
//   - RETRY IS NOT A V2 ACTION. A failed/partial job's retry requires a SIGNED principal (the
//     existing binding); V2 signs nothing (#293). So retry here is a RECOMMENDATION that routes to
//     the authorized surface — never a V2-initiated write. Hiding the affordance would assert an
//     authority model; inventing a signed write in V2 would replace a conserved contract. We do
//     neither: we surface the recommendation truthfully and let authority live where it lives.
//   - NOT-PROVISIONED is explicit: stage2a_enabled=false means Stage 2A is not provisioned for the run
//     (no generation command available) — a real, non-erroring empty state, never a spinner and never a failure.
//
// States are genuine reads from the real path (binding-preview rule): loading is the real in-flight
// read, empty/fallback are real results, error is the real upstream/typed failure with a retry.

import { useCallback, useEffect, useRef, useState } from "react";
import { readJson, ReadError, type TopicGenerationReadModel } from "@/lib/read-model";
import TopicItemPanel from "@/components/topic-item-panel";

const PHASE_LABEL: Record<string, string> = {
  empty: "No generation yet",
  awaiting_trigger: "Awaiting manual trigger",   // #310 — manual entry mode, pending the Generate action
  queued: "Queued",
  running: "Generating…",
  partial: "Partially generated",
  failed: "Generation failed",
  completed: "Generated",
};

function phaseLabel(phase: string): string {
  return PHASE_LABEL[phase] ?? phase;
}

/** #310 §F — run-scoped. `roundId` is canonical server identity, carried verbatim into the read
 *  path; never parsed, derived, or reinterpreted here. */
export function GenerationSeam({ roundId }: { roundId: string }) {
  const [model, setModel] = useState<TopicGenerationReadModel | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // #286 latest-wins guard: only the newest read may commit, so a slower earlier read can never
  // overwrite a newer one if the route re-mounts or the run changes quickly.
  const seq = useRef(0);

  const load = useCallback(async (rid: string) => {
    const s = ++seq.current;
    const latest = () => s === seq.current;
    setLoading(true);
    setErr(null);
    setModel(null);
    try {
      const m = await readJson<TopicGenerationReadModel>(
        `/gw/rounds/${encodeURIComponent(rid)}/generation`,
      );
      if (latest()) setModel(m);
    } catch (e) {
      if (latest()) setErr(e instanceof ReadError ? e.message : "read failed");
    } finally {
      if (latest()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(roundId);
  }, [roundId, load]);

  return (
    <section
      data-testid="wb-generation-seam"
      className="rounded-xl border border-(--color-border) bg-(--color-card) p-3"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-(--color-muted)">
          Topic generation
        </h2>
        {model && (
          <span
            data-testid="wb-generation-phase"
            data-phase={model.phase}
            className="rounded-full border border-(--color-border) px-2 py-0.5 text-[10px] text-(--color-fg)"
          >
            {phaseLabel(model.phase)}
          </span>
        )}
        {model && (
          <span data-testid="wb-generation-counts" className="text-[11px] text-(--color-muted)">
            {model.counts.generated}/{model.counts.accepted} topics
          </span>
        )}
        <button
          data-testid="wb-generation-refresh"
          onClick={() => load(roundId)}
          className="ms-auto rounded-md border border-(--color-border) px-2 py-1 text-[11px] font-medium text-(--color-fg) hover:bg-(--color-bg)"
        >
          Refresh
        </button>
      </div>

      {/* OBSERVE framing — this seam reports; it never starts or retries generation itself. */}
      <p
        data-testid="wb-generation-observe-note"
        className="mb-3 rounded-lg border border-(--color-border) bg-(--color-bg) px-3 py-2 text-[11px] text-(--color-muted)"
      >
        Read-only view of the governed Topic run. Starting or retrying generation is a governed,
        authorized action performed on the authorized surface — this lane observes and reports it.
      </p>

      {err ? (
        <div data-testid="wb-generation-error" className="text-xs text-(--color-danger)">
          <p className="mb-2">Could not read generation for {roundId}: {err}</p>
          <button
            data-testid="wb-generation-retry-read"
            onClick={() => load(roundId)}
            className="rounded-md border border-(--color-border) px-2 py-1 font-medium text-(--color-fg) hover:bg-(--color-bg)"
          >
            Retry
          </button>
        </div>
      ) : loading ? (
        <p data-testid="wb-generation-loading" className="text-xs text-(--color-muted)">
          Loading generation for {roundId}…
        </p>
      ) : !model ? null : !model.stage2a_enabled ? (
        <p data-testid="wb-generation-fallback" className="text-xs text-(--color-muted)">
          Stage 2A Topic generation is not provisioned for this run — no generation command is
          available. Nothing to show; this is a real, governed state, not a failure.
        </p>
      ) : model.jobs.length === 0 ? (
        <p data-testid="wb-generation-empty" className="text-xs text-(--color-muted)">
          No Topic generation has run for {roundId} yet. This is a real empty result.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {/* ---- durable job truth ---- */}
          <ul data-testid="wb-generation-jobs" className="flex flex-col gap-2">
            {model.jobs.map((j) => (
              <li
                key={j.job_id}
                data-testid={`wb-generation-job-${j.job_id}`}
                data-status={j.status}
                className="rounded-lg border border-(--color-border) px-3 py-2 text-[11px]"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="rounded-full border border-(--color-border) px-2 py-0.5 text-[10px] text-(--color-fg)">
                    {j.status}
                  </span>
                  <span className="text-(--color-muted)">
                    {(j.slots_done ?? 0)} done · {(j.slots_failed ?? 0)} failed ·{" "}
                    {(j.slots_total ?? 0)} total
                  </span>
                  {j.accepted_schedule_token != null && (
                    <span className="text-(--color-muted)">token {j.accepted_schedule_token}</span>
                  )}
                </div>
                {j.error_detail != null && (
                  <p data-testid="wb-generation-job-error" className="mt-1 text-(--color-danger)">
                    {typeof j.error_detail === "string"
                      ? j.error_detail
                      : JSON.stringify(j.error_detail)}
                  </p>
                )}
                {(j.status === "failed" || j.status === "partial") && (
                  <p
                    data-testid="wb-generation-retry-recommendation"
                    className="mt-1 text-(--color-muted)"
                  >
                    Recommended: retry this run from the authorized surface — a governed, attributed
                    action. This lane cannot retry it (it holds no authority).
                  </p>
                )}
              </li>
            ))}
          </ul>

          {/* ---- per-accepted-slot results ---- */}
          <ul data-testid="wb-generation-results" className="flex flex-col gap-2">
            {model.results.map((r) => (
              <li
                key={r.slot_id}
                data-testid={`wb-generation-result-${r.slot_id}`}
                className="rounded-lg border border-(--color-border) px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-(--color-muted)">
                  {/* accepted schedule facts */}
                  <span className="font-mono text-xs font-medium text-(--color-fg)">{r.slot_id}</span>
                  <span>
                    {[r.accepted.pillar_code, r.accepted.hcs_id, r.accepted.format]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                  {r.slot_status && (
                    <span className="rounded-full border border-(--color-border) px-2 py-0.5 text-[10px]">
                      {r.slot_status}
                    </span>
                  )}
                </div>

                {r.topic ? (
                  <div className="mt-1">
                    {/* #315 — the Arabic topic title is bidi-isolated with a truthful per-node lang so
                        mixed LTR/RTL neighbours (identity/provenance) never reorder it. */}
                    <p className="text-sm text-(--color-fg)" data-testid="wb-generation-topic-title">
                      {r.topic.title ? (
                        <bdi lang="ar" dir="auto">{r.topic.title}</bdi>
                      ) : (
                        "—"
                      )}
                    </p>
                    {r.topic.meaning && (
                      <p className="text-xs text-(--color-muted)">
                        {/* #315 ruling 3 — title AND meaning are Arabic source; declare lang="ar" per node
                            so assistive tech never reads the Arabic gloss with the English chrome voice. */}
                        <bdi lang="ar" dir="auto">{r.topic.meaning}</bdi>
                      </p>
                    )}
                    {/* canonical Topic identity — server truth, verbatim */}
                    <p className="mt-0.5 font-mono text-[10px] text-(--color-muted)">
                      topic {r.topic.topic_id} · rev {r.topic.revision}
                    </p>
                    {/* provenance DISCLOSURE — what actually ran */}
                    {r.provenance && (
                      <p
                        data-testid="wb-generation-provenance"
                        className="mt-0.5 text-[10px] text-(--color-muted)"
                      >
                        {[
                          r.provenance.resolved_provider && `via ${r.provenance.resolved_provider}`,
                          r.provenance.resolved_model,
                          r.provenance.execution_route,
                          r.provenance.novelty_brief_version &&
                            `novelty ${r.provenance.novelty_brief_version}`,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                    {/* #313 — canonical per-item Topic governance (inspect/history + typed-action edit) */}
                    <TopicItemPanel slotId={r.slot_id} />
                  </div>
                ) : (
                  <p
                    data-testid="wb-generation-result-pending"
                    className="mt-1 text-[11px] text-(--color-muted)"
                  >
                    Accepted; no Topic generated yet.
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
