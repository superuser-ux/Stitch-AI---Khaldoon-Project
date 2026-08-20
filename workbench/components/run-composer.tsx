"use client";

// #376 — the ONE ephemeral run composer, and the governed recommendation it consumes.
//
// WHAT REPLACED WHAT. Until now the root carried a detached Create-run form with its own `Days` and
// an optional start date, and a calendar that could not start anything. Two surfaces described the
// same intent and neither agreed with the other: an operator picked dates on the calendar and then
// retyped a duration into a form. This component is the single composer all three entry paths reach —
// date click, inclusive range selection, and the explicit New run button — so there is exactly one
// draft, one preview and one submit.
//
// THE INCLUSIVE RANGE IS THE DURATION. There is no independent `days` field to contradict it: days
// are DERIVED from [start .. end] inclusive. The planner's contract still takes `days`, and the
// authority independently re-checks `days × posts_per_day` and `starts_on` against the proposal —
// so a composer that miscomputed the range is REFUSED upstream rather than quietly accepted.
//
// EPHEMERAL MEANS EPHEMERAL (GPT amendment 4). A date gesture initializes client state and NOTHING
// else: no reserved identifier, no round, no slots, no audit row, no upstream request at all. The
// only two upstream calls this component can make are both explicit operator actions with visible
// controls — "Get recommended mix" and "Plan run" — and closing the composer discards the draft.
//
// PREVIEW IS SIDE-EFFECT-FREE; ONLY PLAN RUN CREATES ANYTHING (GPT amendment 4, #376 correction).
// "Get recommended mix" calls the SIDE-EFFECT-FREE preview (`/gw/run-mix-recommendation-preview`),
// which persists no proposal, no audit row and no reserved identifier — it is a pure calculation the
// operator inspects. The durable single-use PROPOSAL FENCE (and the run) are minted ONLY by the
// explicit Plan run: on submit this creates the proposal, gated on the previewed generations still
// being current, then binds it into the round. So before submit there is genuinely no durable state,
// and "Nothing is created until you plan the run" is now literally true after a recommendation too.
//
// The draft still never shows a blank/zero/unexplained mix: before the operator requests it there are
// no mix inputs and submit is disabled with a stated reason; after it, the mix shown is the governed
// one with its rationale and generation provenance (the proposal id does not exist yet — it is minted
// on submit, and the snapshot then binds recommendation, submission and generations immutably).
//
// FAIL CLOSED ON DRIFT (amendment 5). The preview carries the governed-generation fingerprint it was
// computed under. On submit that fingerprint is handed to proposal creation, which refuses (typed
// `recommendation_stale`) and persists nothing if a policy/methodology/workflow activation moved the
// world in between — the operator then reviews the refreshed recommendation rather than silently
// planning against numbers they never saw.
//
// V2 COMPUTES NO MIX. Every count, the rationale, the provenance identifiers and the blocked reasons
// come from the canonical authority verbatim. There is no equal-distribution fallback, no client
// heuristic, no cached default: when the authority is blocked, submit is DISABLED and the typed
// reason is displayed — the draft is preserved so nothing the operator did is lost.

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { postJson, WriteError } from "@/lib/read-model";

/** How the draft was started. Presentation/provenance only — it never reaches the server. */
export type ComposerSource = "date-click" | "range" | "new-run";

export type ComposerDraft = {
  readonly source: ComposerSource;
  /** Inclusive ISO dates. `endsOn === startsOn` for a one-day draft. */
  readonly startsOn: string;
  readonly endsOn: string;
};

/** The authority's typed answer, rendered verbatim. V2 defines no shape of its own here.
 *
 *  This is the SIDE-EFFECT-FREE PREVIEW result: it carries no proposal id, no row digest and no expiry
 *  because no proposal exists yet. `preview_fingerprint` is the governed-generation identity the numbers
 *  were computed under; it is handed back on submit so the authority can refuse a stale plan. */
type Recommendation = {
  status: "recommended";
  preview_fingerprint: Record<string, unknown>;
  starts_on: string;
  ends_on: string;
  days: number;
  posts_per_day: number;
  expected_slots: number;
  recommended_mix: Record<string, number>;
  rationale: {
    statement?: string;
    algorithm?: string;
    authority_version?: string;
    model_posture?: string;
    allocated?: Record<string, number>;
    excluded_versions?: { version_id: string; reason: string }[];
    policy_notes?: string | null;
    [k: string]: unknown;
  };
  authority_version: string;
  algorithm: string;
  model_posture: string;
  policy: { policy_id: string; generation: number };
  baseline_policy: { policy_id: string; generation: number };
  methodology_version?: string | null;
  workflow_version?: string | null;
};

type Blocked = { status: "blocked"; reason: string; detail?: string; [k: string]: unknown };

type MixState =
  | { kind: "none" }
  | { kind: "busy" }
  | { kind: "recommended"; rec: Recommendation }
  | { kind: "blocked"; blocked: Blocked }
  | { kind: "stale"; msg: string }
  | { kind: "error"; msg: string };

type Feedback = { kind: "idle" | "busy" | "error" | "conflict"; msg?: string };

/** Inclusive day count. The single place duration is derived; both the preview and the submitted
 *  `days` read it, so they cannot disagree with each other. */
export function inclusiveDays(startsOn: string, endsOn: string): number {
  const a = Date.parse(`${startsOn}T00:00:00Z`);
  const b = Date.parse(`${endsOn}T00:00:00Z`);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return 0;
  return Math.round((b - a) / 86_400_000) + 1;
}

/** The inclusive dates the draft covers, for the coverage preview. Bounded so a pathological range
 *  cannot render an unbounded list. */
export function coverageDates(startsOn: string, endsOn: string, limit = 10): string[] {
  const n = inclusiveDays(startsOn, endsOn);
  const out: string[] = [];
  for (let i = 0; i < Math.min(n, limit); i++) {
    const d = new Date(`${startsOn}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + i);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

type Props = {
  draft: ComposerDraft;
  /** Discards the draft entirely. Nothing durable was created, so there is nothing to clean up. */
  onCancel: () => void;
  /** Lets the operator adjust the range without leaving the composer (still ephemeral). */
  onRangeChange: (startsOn: string, endsOn: string) => void;
};

export function RunComposer({ draft, onCancel, onRangeChange }: Props) {
  const router = useRouter();
  const [postsPerDay, setPostsPerDay] = useState(2);
  const [label, setLabel] = useState("");
  const [mixState, setMixState] = useState<MixState>({ kind: "none" });
  /** The operator's amendment of the governed mix. Seeded FROM the recommendation, never from zero. */
  const [mix, setMix] = useState<Record<string, number>>({});
  const [fb, setFb] = useState<Feedback>({ kind: "idle" });
  /** The proposal minted on the FIRST Plan run, reused across retries of the SAME submission. Creating
   *  a fresh proposal per retry would scope the idempotency key to a new proposal and could plan two
   *  runs; caching it here keeps a retry converging on one run. Cleared whenever the draft changes. */
  const proposalRef = useRef<{ proposal_id: string } | null>(null);
  /** Stable across retries of the SAME submission, so a retry converges on one run instead of two. */
  const idemRef = useRef<string>("");
  const seq = useRef(0);

  const days = inclusiveDays(draft.startsOn, draft.endsOn);
  const expectedSlots = days * postsPerDay;

  // Any change to what was recommended INVALIDATES the recommendation: a proposal is bound to an
  // exact range and slot total, so keeping it on screen after the operator moved the dates would
  // display provenance that no longer describes the draft. The authority would refuse the bind
  // anyway (typed `proposal_context_mismatch`); discarding here means the operator sees the honest
  // state — "not requested for this range yet" — instead of a stale recommendation.
  useEffect(() => {
    setMixState((s) => (s.kind === "none" ? s : { kind: "none" }));
    setMix({});
    idemRef.current = "";
    proposalRef.current = null;               // a changed draft invalidates any minted proposal
  }, [draft.startsOn, draft.endsOn, postsPerDay]);

  const requestRecommendation = useCallback(async () => {
    const mine = ++seq.current;
    setMixState({ kind: "busy" });
    setFb({ kind: "idle" });
    // A re-preview supersedes any proposal minted by a prior (failed/stale) submit: the operator is
    // asking for fresh numbers, so nothing durable from before may be reused.
    proposalRef.current = null;
    idemRef.current = "";
    try {
      // SIDE-EFFECT-FREE preview (amendment 4): this persists no proposal, no audit and no identifier.
      const res = await postJson<Recommendation | Blocked>("/gw/run-mix-recommendation-preview", {
        starts_on: draft.startsOn, ends_on: draft.endsOn, posts_per_day: postsPerDay,
      });
      if (mine !== seq.current) return;
      if (res.status === "blocked") {
        // A REAL governed state, not a UI failure: nothing was persisted, so there is no proposal to
        // submit and submit stays disabled. The draft is untouched.
        setMixState({ kind: "blocked", blocked: res as Blocked });
        return;
      }
      const rec = res as Recommendation;
      setMixState({ kind: "recommended", rec });
      // The governed counts ARE the starting mix. The operator amends from the recommendation, never
      // from an empty or zero allocation.
      setMix({ ...rec.recommended_mix });
    } catch (e) {
      if (mine !== seq.current) return;
      setMixState({ kind: "error", msg: e instanceof WriteError ? e.message : "tanaghom api unreachable" });
    }
  }, [draft.startsOn, draft.endsOn, postsPerDay]);

  const rec = mixState.kind === "recommended" ? mixState.rec : null;
  const mixTotal = Object.values(mix).reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
  const amended = !!rec && JSON.stringify(mix) !== JSON.stringify(rec.recommended_mix);

  const submit = async () => {
    if (!rec) return;
    setFb({ kind: "busy", msg: "Planning run…" });
    const format_mix: Record<string, number> = {};
    for (const [k, v] of Object.entries(mix)) if (v > 0) format_mix[k] = v;
    try {
      // STEP 1 — mint the durable proposal, but ONLY now, on this explicit Plan run (amendment 4), and
      // ONLY if not already minted by a prior attempt of THIS submission (so a retry converges on one
      // run). `expected` carries the previewed generation fingerprint: if the world moved since the
      // preview, the authority refuses with a typed `recommendation_stale` and persists nothing.
      if (!proposalRef.current) {
        const proposal = await postJson<{ proposal_id: string; digest: string }>("/gw/run-mix-proposals", {
          starts_on: draft.startsOn, ends_on: draft.endsOn, posts_per_day: postsPerDay,
          expected: rec.preview_fingerprint,
        });
        proposalRef.current = { proposal_id: proposal.proposal_id };
        idemRef.current = `${proposal.proposal_id}:${(proposal.digest || "").slice(0, 16)}`;
      }
      // STEP 2 — bind the proposal into the run. The planner re-verifies the generations and the
      // proposal context independently, so this fails closed a second way if anything drifts.
      const res = await postJson<{ round_id: string; total?: number }>("/gw/rounds", {
        days, posts_per_day: postsPerDay, starts_on: draft.startsOn, format_mix,
        proposal_id: proposalRef.current.proposal_id, idempotency_key: idemRef.current,
        ...(label.trim() ? { label: label.trim() } : {}),
      });
      // RNG-01 — open the created run FOCUSED ON ITS OWN RANGE. `focus=range` asks the workspace to
      // resolve the window from the SERVER's accepted `starts_on`/`period_len_days`, so the calendar
      // shows what was accepted rather than what this client proposed.
      router.push(`/runs/${encodeURIComponent(res.round_id)}?stage=schedule_review&focus=range`);
    } catch (e) {
      if (e instanceof WriteError) {
        // A stale recommendation is a distinct, fail-closed state: the generations moved between the
        // preview and this submit. Nothing was persisted; the operator must re-request the refreshed
        // recommendation before planning. Surface it as its own blocked-style state, not a generic
        // error, and drop any half-minted proposal so the next attempt starts clean.
        if (e.code === "recommendation_stale") {
          proposalRef.current = null; idemRef.current = "";
          setMixState({ kind: "stale", msg: e.message });
          setFb({ kind: "idle" });
          return;
        }
        // Every other typed refusal verbatim: a superseded policy/baseline/methodology generation
        // caught at bind, an expired or already-consumed proposal, a context mismatch, or the planner's
        // own 422. The draft is preserved so the operator can review and decide again.
        setFb({ kind: e.status === 409 ? "conflict" : "error", msg: e.message });
        return;
      }
      setFb({ kind: "error", msg: "tanaghom api unreachable" });
    }
  };

  const rangeValid = days > 0;

  return (
    <section
      data-testid="run-composer"
      data-source={draft.source}
      data-starts-on={draft.startsOn}
      data-ends-on={draft.endsOn}
      data-days={days}
      data-expected-slots={expectedSlots}
      aria-label="Compose run"
      className="flex flex-col gap-3 rounded-xl border border-(--color-border) bg-(--color-card) p-3 text-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">New run</h2>
        <span data-testid="composer-source-note" className="text-(--color-muted)">
          {draft.source === "range"
            ? "Started from a selected date range."
            : draft.source === "date-click"
              ? "Started from a clicked date."
              : "Started from New run."}
          {" "}Nothing is created until you plan the run.
        </span>
        <button
          type="button"
          data-testid="composer-cancel"
          onClick={onCancel}
          className="ms-auto rounded-md border border-(--color-border) px-2 py-1"
        >
          Discard draft
        </button>
      </div>

      {/* The inclusive range IS the duration — there is no separate days input to contradict it. */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span>Start (inclusive)</span>
          <input
            data-testid="composer-starts-on" type="date" value={draft.startsOn}
            onChange={(e) => onRangeChange(e.target.value, draft.endsOn)}
            className="rounded-md border px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>End (inclusive)</span>
          <input
            data-testid="composer-ends-on" type="date" value={draft.endsOn}
            onChange={(e) => onRangeChange(draft.startsOn, e.target.value)}
            className="rounded-md border px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Posts / day</span>
          <input
            data-testid="composer-posts" type="number" min={1} max={24} value={postsPerDay}
            onChange={(e) => setPostsPerDay(Math.min(24, Math.max(1, Number(e.target.value) || 1)))}
            className="w-20 rounded-md border px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Label (optional)</span>
          <input
            data-testid="composer-label" type="text" value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="w-48 rounded-md border px-2 py-1"
          />
        </label>
      </div>

      {/* Preview (GPT amendment 5): inclusive dates, duration, posts/day, expected slots, coverage. */}
      <div data-testid="composer-preview" data-days={days} data-slots={expectedSlots}
           className="rounded-md border p-2">
        {rangeValid ? (
          <>
            <p>
              <strong data-testid="composer-preview-range">{draft.startsOn} → {draft.endsOn}</strong>{" "}
              · <span data-testid="composer-preview-days">{days} day{days === 1 ? "" : "s"}</span>
              {" "}· <span data-testid="composer-preview-posts">{postsPerDay}/day</span>
              {" "}· <span data-testid="composer-preview-slots">{expectedSlots} slots</span>
            </p>
            <p data-testid="composer-preview-coverage" className="mt-1 text-(--color-muted)">
              Covers {coverageDates(draft.startsOn, draft.endsOn).join(", ")}
              {days > 10 ? `, … (${days} days in total)` : ""}
            </p>
          </>
        ) : (
          <p data-testid="composer-preview-invalid" className="text-(--color-danger)">
            The end date is before the start date — adjust the range. The run is not planned.
          </p>
        )}
      </div>

      {/* The governed mix. V2 never authors one. */}
      <div data-testid="composer-mix" data-state={mixState.kind} className="flex flex-col gap-2 rounded-md border p-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-medium">Framework mix</h3>
          {rec && (
            <span data-testid="composer-mix-total" data-total={mixTotal} data-target={rec.expected_slots}
                  className="text-(--color-muted)">{mixTotal} / {rec.expected_slots} slots</span>
          )}
          <button
            type="button"
            data-testid="composer-recommend"
            disabled={!rangeValid || mixState.kind === "busy"}
            onClick={() => void requestRecommendation()}
            className="ms-auto rounded-md border px-2 py-1 disabled:opacity-50"
          >
            {mixState.kind === "none" ? "Get recommended mix" : "Recalculate recommendation"}
          </button>
        </div>

        {mixState.kind === "none" && (
          <p data-testid="composer-mix-unrequested" className="text-(--color-muted)">
            No mix yet. The recommendation comes from the governed run-mix policy — this surface never
            proposes one of its own, and a run cannot be planned until the authority has answered.
          </p>
        )}

        {mixState.kind === "busy" && (
          <p data-testid="composer-mix-busy" className="text-(--color-muted)">Asking the run-mix authority…</p>
        )}

        {mixState.kind === "error" && (
          <p data-testid="composer-mix-error" className="text-(--color-danger)">{mixState.msg}</p>
        )}

        {/* Fail-closed drift: the governed generations moved between preview and submit. Nothing was
            planned; the operator must re-request the refreshed recommendation. */}
        {mixState.kind === "stale" && (
          <div data-testid="composer-mix-stale"
               className="rounded-(--radius-sm) border border-(--color-warn) bg-(--color-warn-soft) p-2 text-(--color-fg)">
            <p>{mixState.msg}</p>
            <p className="mt-1 text-(--color-muted)">
              No run was created. Request the recommendation again to see the refreshed governed mix,
              then plan the run against it.
            </p>
          </div>
        )}

        {/* MIX-03 — a typed BLOCKED state. Nothing was persisted, submit is disabled, draft intact. */}
        {mixState.kind === "blocked" && (
          <div data-testid="composer-mix-blocked" data-reason={mixState.blocked.reason}
               className="rounded-(--radius-sm) border border-(--color-danger) bg-(--color-danger-soft) p-2 text-(--color-fg)">
            <p>
              No governed recommendation is available: <code>{mixState.blocked.reason}</code>
            </p>
            <p className="mt-1">{String(mixState.blocked.detail ?? "")}</p>
            <p className="mt-1 text-(--color-muted)">
              Your draft is preserved. Planning stays disabled — this surface will not substitute an
              equal split, a remembered default, or any mix of its own.
            </p>
          </div>
        )}

        {rec && (
          <>
            <ul data-testid="composer-mix-inputs" className="flex flex-col gap-1">
              {Object.keys(rec.recommended_mix).map((name) => (
                <li key={name} className="flex flex-wrap items-center gap-2">
                  <label className="min-w-[10rem]" htmlFor={`composer-mix-${name}`}>{name}</label>
                  <input
                    id={`composer-mix-${name}`} data-testid={`composer-mix-${name}`}
                    data-recommended={rec.recommended_mix[name]}
                    type="number" min={0} value={mix[name] ?? 0}
                    onChange={(e) => setMix((m) => ({ ...m, [name]: Math.max(0, Number(e.target.value) || 0) }))}
                    className="w-20 rounded-md border px-2 py-1"
                  />
                  <span className="text-(--color-muted)">recommended {rec.recommended_mix[name]}</span>
                </li>
              ))}
            </ul>

            {amended && (
              <p data-testid="composer-mix-amended" className="text-(--color-muted)">
                Amended from the recommendation. Both the recommendation and your submitted mix are
                recorded with the run.
              </p>
            )}

            {/* Rationale + immutable provenance, rendered from the authority's own payload. */}
            <div data-testid="composer-rationale" className="rounded-md border p-2 text-[11px]">
              <p data-testid="composer-rationale-statement">{rec.rationale.statement}</p>
              <p className="mt-1 text-(--color-muted)">
                <span data-testid="composer-rationale-algorithm">{rec.algorithm}</span>
                {" · "}
                <span data-testid="composer-rationale-authority">{rec.authority_version}</span>
                {" · model: "}
                <span data-testid="composer-rationale-model-posture">{rec.model_posture}</span>
              </p>
              <p data-testid="composer-provenance"
                 data-policy-id={rec.policy.policy_id}
                 data-policy-generation={rec.policy.generation}
                 data-baseline-generation={rec.baseline_policy.generation}
                 className="mt-1 font-mono opacity-70">
                policy gen {rec.policy.generation} · baseline gen {rec.baseline_policy.generation}
                {" "}· proposal minted on Plan run
              </p>
              {(rec.rationale.excluded_versions?.length ?? 0) > 0 && (
                <p data-testid="composer-rationale-excluded" className="mt-1 text-(--color-muted)">
                  {rec.rationale.excluded_versions!.length} weighted framework version(s) are outside
                  the current baseline eligibility and were not allocated.
                </p>
              )}
            </div>
          </>
        )}
      </div>

      <div data-testid="composer-feedback" data-kind={fb.kind} role="status" aria-live="polite"
           className="min-h-[1.25rem] text-(--color-danger)">
        {fb.kind === "busy" ? <span className="text-(--color-muted)">{fb.msg}</span>
          : fb.kind !== "idle" ? fb.msg : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          data-testid="composer-submit"
          disabled={!rec || !rangeValid || fb.kind === "busy"}
          onClick={() => void submit()}
          className="rounded-md border border-(--color-border) px-3 py-1.5 text-sm font-medium hover:bg-(--color-bg) disabled:opacity-50"
        >
          Plan run
        </button>
        {!rec && (
          <span data-testid="composer-submit-disabled-reason" className="text-(--color-muted)">
            Planning needs a governed recommendation first.
          </span>
        )}
      </div>
    </section>
  );
}
