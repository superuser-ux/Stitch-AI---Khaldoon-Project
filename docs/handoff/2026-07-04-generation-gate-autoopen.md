# Handoff — generation review gate does not auto-open under load

> ✅ **RESOLVED (2026-07-05) — do NOT apply the "retry auto-open on the normal path" fix below.**
> The generate flow was intentionally moved to a **two-stage** model: normal completion (the `/jobs`
> poll confirms done) surfaces the manual **"Start review"** control; auto-open is kept **only** as the
> `/jobs`-unavailable fallback (`generate()` → `settle("done", { autoOpen: !jobsReachable })` in
> `dashboard/lib/review-context.tsx`). The release specs were updated together to match (they now click
> `enterActiveReview`/`open-gate` on the normal path and assert cards auto-appear only in the
> `/jobs`-unavailable test) — satisfying the guardrail below. Because the normal path no longer attempts
> auto-open, the single-missed-auto-open stall cannot occur there. Verified under the exact flaky repro:
> **full Chromium pack `npx playwright test --project=chromium` → 37/37 green (2026-07-05)**, including
> `runs-and-generation:111` (jobs-registry-unavailable fallback), `schedule-and-topic-surface`,
> `content-handoff-flow`, and all `review-iteration` (rework re-entry) specs. The "related" `regenerate()`
> fragility is also resolved — it uses `reworkLanded()` (DB truth) → `settle` → `resumeReviewIfNeeded()`.
> The historical analysis below is preserved for context only.

**Date:** 2026-07-04 · **Branch:** feat/lunaris-redesign · **Relates to:** #1 (release gate), #4 (generation hardening)

> ⚠️ **Concurrency note.** This was diagnosed while a second session was editing
> `dashboard/lib/review-context.tsx` (a `[gen-poll]` console.log and `e2e/_diag.spec.ts` appeared
> mid-investigation). To avoid clobbering, **this session made NO edits to `review-context.tsx`.**
> This note preserves the root cause + fix direction for whoever owns that file.

## Symptom (real product bug, flaky under load)

Full Chromium pack: 4 failing specs, all in the generate → review path
(`schedule-and-topic-surface:102`, `content-handoff-flow`, `runs-and-generation:107` & the new
`/jobs`-registry test). They **pass in isolation, fail under pack load** — the intermittent,
load-dependent failure originally described on #1.

After generation completes, the stage lands and **stays** at:

- `next_action = start_review`
- `review_pending = 2`
- `gate_id = null`

and the review never surfaces its cards.

## Root cause (confirmed with evidence)

Job-completion detection is **already robust** — `generate()` uses `stageReady()` (DB stage state,
`next_action !== "generate"`) as the authoritative signal and only uses `/jobs` for the progress bar.
That part is fine and should stay.

The remaining defect is **the auto-open step, not completion detection.** In 4/4 reproductions the
network trace shows the topic stage reach `start_review / rp=2 / gid=null` and then **no
`POST /gates` for the topic stage is ever issued** — so `resumeReviewIfNeeded()` (the only thing that
opens the review gate so cards render) does not run to completion.

In the current code `settle("done")` opens the gate only inside its `if (current)` branch, where
`current = isCurrentStageContext(genRound, genGate)`. The evidence (settle fires — the "Generated N
item(s)" toast shows — but no `POST /gates`) indicates that branch is skipped / the open call is lost,
and **nothing retries it**: `refreshBurst()` afterwards only re-reads state (`load`/`loadRounds`),
never re-attempts the open. So a single missed auto-open is terminal → the stage is stuck on the
"Start review" affordance with `gate_id` still null.

**In short:** completion is detected, but the gate auto-open is a single-shot that can be skipped/lost
and is never retried.

## Recommended fix direction (keep AUTO-OPEN behavior)

1. Make surfacing **idempotent and retried until observed**: after generation completes, keep calling
   `resumeReviewIfNeeded()` (which is safe — it no-ops when `gate_id` is set or `review_pending === 0`)
   until the stage reports an open `gate_id`, or a bounded cap elapses. Reuse the existing `refreshBurst`
   cadence, but have it **re-attempt the open**, not just re-read state.
2. Do **not** leave the open permanently gated behind a one-shot `isCurrentStageContext` check that can
   skip it forever. If the operator is still on the stage, the gate must end up open.
3. Verify with the two release tests as written (they assert cards / "topic code" auto-appear, no manual
   click): `dashboard/e2e/runs-and-generation.spec.ts` ("...resurfaces the review when the /jobs registry
   is unavailable") and `dashboard/e2e/schedule-and-topic-surface.spec.ts:102`.

## ⚠️ Product-behavior guardrail — do not silently switch to manual-only

A mid-flight edit in the other session changed `settle` to **not** auto-open and instead surface a
manual "Start review" button (comment: "do NOT auto-open the gate here"). **That is a product behavior
change, not a robustness fix.** The current suite and the user flow both assume the review gate
**auto-surfaces** when generation completes:

- `schedule-and-topic-surface.spec.ts:102` waits for `/topic code/i` (a rendered card) **before** any
  click.
- `content-handoff-flow` and `runs-and-generation` similarly assert cards appear on their own.

If manual-only entry is genuinely desired, it must be an explicit product decision with the tests and
UX expectations changed **together** — not landed as a side effect of a stall fix. Otherwise those
specs stay red.

## Related (same bug class, out of this scope — belongs with rework / #4)

`regenerate()` (the rework path) still has the **old fragile poll**: `/jobs` is treated as the
authoritative completion signal, and on repeated `/jobs` failure it bails to
`refreshBurst([0,2000,5000])` **without** calling `resumeReviewIfNeeded()` — so a rework that finishes
in the DB while `/jobs` is flaky can leave the stage unsurfaced, same as the original generate bug.
Worth applying the same DB-state fallback there once generate is settled.

## Reproduction

```
cd dashboard
npx playwright test runs-and-generation.spec.ts --project=chromium   # flaky: 107/111 fail under load
# or full pack:
npx playwright test --project=chromium
```
Gate API must run with `TANAGHOM_WRITER_STUB=1` (deterministic writer); dashboard prod build on :3000.
