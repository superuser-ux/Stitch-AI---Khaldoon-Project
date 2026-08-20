# Design — UI-driven runs, generation jobs, and a unified stage action surface

**Date:** 2026-06-30
**Status:** Approved (design); pending spec review
**Branch (to be created):** `feat/ui-driven-runs`

## Problem

The dashboard only drives **review/approval gates**. Two operator-only steps have no UI affordance:

1. **Run configuration** — the round's size (days × posts/day) is set in `system_config.yaml` / via the
   `plan_round` CLI. The reviewer can't start a run from the UI.
2. **Generation** — topic and script *writing* are CLI batch jobs (`run_writers topics|scripts`). After
   approving topics, the reviewer is stranded: the Script stage shows a misleading empty state and there is
   no way to trigger script generation.

Concretely observed on round R1: 4 topics approved + `topic→script` directives emitted, but the Script
stage rendered `✓ Review complete — 0 advanced` (a read-model quirk) with the static copy
"Start the review to load Script for R1" and no actionable control. The reviewer had no path forward.

## Goals

- Start a run from the UI: **Days** (default 28) + **Posts/day** (default 2), open numeric range (min 1).
- Trigger generation from the UI as **background jobs with live progress**, for every stage that has a
  generator; surface a consistent action for the manual/external stages too (all 8 stages).
- Fix the misleading empty-state copy and the `complete`-when-nothing-produced stage-state quirk.
- Keep all existing suites green; reset the dry run to a clean slate so the new flow is the entry point.

## Non-goals

- Building real generators for production / media-edit / distribution (AVP / POSTIZ are post-v1). Those
  stages keep their existing **manual DAM upload** affordance; this work only makes it consistent.
- The serious UX redesign — captured here as **Phase 2**, done as its own design cycle after Phase 1.

---

## Approach decisions (chosen)

- **Generation = background job + live progress.** Click → job starts server-side, returns immediately;
  the UI polls a status endpoint and shows `generating… 3/6`, then items appear. Robust for 5 or 56 slots.
- **Progress = DB-derived, not writer callbacks.** A job's `done` count = number of slots that reached the
  stage's output status. Decoupled from writer internals; reuses the read model. Extends the *existing*
  in-process daemon-thread pattern already used by the `/rounds/{id}/rework` endpoint.
- **Planner sizing = ratios + largest-remainder rounding.** The configured pillar/format distributions are
  interpreted as proportions and scaled to `total = days × posts_per_day`, distributing integer remainders
  so counts sum exactly. **28×2 reproduces today's exact 22/17/9/4/4 = 56** — no change to the default.
- **Run flow = plan only, then generate per stage.** The form creates the planned round (slots `RESERVED`);
  the Topic stage then shows **Generate topics**. Consistent with the all-8-stages model.

---

## Phase 1 — components

### 1. Planner: parametric run sizing
- `planner/plan_round.py`: `assign_pillars_formats` (and the validation in `plan`) change from
  "absolute counts must equal total" to **ratio-scaling**. Add a helper `scale_distribution(ratios, total)`
  using largest-remainder so the result is integer and sums to `total`. The weekly format mix scales to
  `posts_per_day × 7` and repeats per week (existing `i % slots_per_week` handles a partial final week).
- The planner accepts `period_len_days` and `posts_per_day` overrides (already parametric via the template;
  add CLI/args + API params). HCS/lens cursor advance is unchanged.
- **Invariant test:** 28×2 yields exactly `{P1:22, P2:17, P3:9, P4:4, P5:4}` (today's numbers).
- **Tiny-run degradation (must not crash).** When `total < number of pillars` (e.g. 1×2 = 2 slots, 5
  pillars), `scale_distribution` must still return a valid integer allocation summing to `total` — the
  largest-ratio pillars win the available slots, smaller ones get 0; no negative counts, no crash, no
  empty `pillar_seq`. The weekly format mix degrades the same way when `posts_per_day × 7 < #formats`.
  **HCS/lens cursor integrity holds across arbitrary sizes:** the cursor advances by exactly the number of
  slots actually assigned per pillar (0-assignment pillars don't advance), so a later run resumes correctly.

### 2. New API endpoints (`gates/api.py`)
- `POST /rounds` — body `{days:int≥1, posts_per_day:int≥1, label?:str}`. Plans a fresh round (next `Rn`),
  returns `{round_id, total}`.
- `POST /rounds/{round_id}/stages/{stage}/generate` — starts a generation job over the stage's pending
  inputs (topic: `RESERVED`; script: `TOPIC_APPROVED` without a draft). Returns `{job_id, total}`.
  503 if the writer module is unavailable (same guard as rework).
- `GET /jobs/{job_id}` — `{job_id, kind, round_id, stage, status: running|done|error, done, total, error?}`.
  `done` is computed live from the DB (count of slots at the stage's output status).

> **Single generation mechanism (shared across surfaces).** These two endpoints are the *one* way to
> trigger generation. The Telegram conversational agent (`feat/telegram-pilot`) drives generation through
> the **same** endpoints/engine contract — there is **no parallel generation path**. Therefore they are
> built **main-mergeable** (no dashboard-only assumptions in the request/response shapes); `feat/telegram-pilot`
> rebases onto this once Phase 1 merges and consumes them as-is. Keep the contract surface (`gates/contract.py`,
> if present) the boundary both the buttons and the agent share.

### 3. Job registry (`gates/jobs.py`, new — small)
- In-process `JOBS: dict[str, Job]`. `start(kind, round_id, stage, total, fn) -> job_id` runs `fn` on a
  daemon thread, marking `done`/`error` on completion. `status(job_id)` returns the record + a live `done`
  count via a DB query supplied by the caller. Bounded; old finished jobs may be evicted (cap ~50).
- The generation endpoints call `run_writers` topic/script entry points inside the job fn (mirrors how
  `/rework` already calls `run_writers.rework_round`).

> **Scope — keep it simple.** In-process daemon-thread jobs are acceptable for now (single operator, low
> volume). A **durable job queue** (Redis/RQ/Celery, persistence across restarts, multi-worker) is a
> later / **if-scale** item — **do NOT build it now.** The DB-derived `done` count is what makes the simple
> version safe: a restart loses only the transient "running" flag, never produced work.

### 4. Unified stage read-model (`gates/engine.py::stage_state`)
- Extend the returned `info` with:
  - `generator`: `ai | manual | external` (from the stage contract / `/stages`).
  - `pending_input`: count of slots whose status is the stage's *input* status but not yet generated
    (topic: `RESERVED`; script: `TOPIC_APPROVED` without a draft).
  - `next_action`: one of `generate | start_review | reviewing | ready_to_commit |
    awaiting_regeneration | upload | complete | empty` — the single source of truth for the UI control.
- **Bug fixes:**
  - Do not report `complete` when nothing was produced at this stage (advanced == 0 and the only nonzero
    count is inherited `dropped`). Such a stage with pending inputs → `generate`; with no inputs → `empty`.
  - Stop the inherited-`dropped` bleed from making downstream stages look acted-upon.

### 5. UI — one action surface + Start-a-run (`dashboard/`)
- **`StageAction` component** (new): renders the control from `stage_state.next_action`:
  - `generate` → "Generate {topics|drafts}" button → `POST …/generate` → progress bar polling `GET /jobs/{id}`
    → on `done`, refresh (items appear).
  - `upload` (manual stages) → existing DAM upload/produce affordance.
  - `start_review | reviewing | ready_to_commit | awaiting_regeneration` → existing disposition bar.
  - `complete | empty` → state-aware text (replaces the static "Start the review to load…" copy in
    `review-surface.tsx`).
- **New-run dialog** in the app shell: Days (default 28) + Posts/day (default 2), open numeric range,
  live "= N posts" preview. Submit → `POST /rounds` → select new round → land on Topic stage.
- `review-context.tsx`: add `plan(days, postsPerDay)`, `generate(stage)`, and job-polling state.
  Reuse `data-testid` hooks so Playwright stays green; add new ones (`new-run`, `days-input`,
  `ppd-input`, `generate-{stage}`, `job-progress`).

### 6. Reset
- Full wipe (rounds/slots/topics/scripts/gates/gate_target/gate_decision/directive/asset/
  slot_approval/slot_review/audit_log + `hcs_cursor`, `lens_history`), methodology reference data
  (42 HCS, lenses, canon, templates) preserved. No round remains — the user starts from the New-run UI.
- **Shared-DB coordination (explicit).** The wipe clears the **shared** Postgres, so it also destroys the
  **Telegram-pilot** session's data (e.g. its `RTG1` round). The reset must therefore be **coordinated**:
  run the wipe, then **both** sessions plan fresh rounds. The reset action (CLI now; any future UI control)
  must carry a **clear warning that it affects ALL sessions on the shared DB** — not just the current one.
- **Destructive → guarded.** Reset permanently deletes work. For now it stays an explicit, **confirmed**
  operator action (not a casual one-click) and is invoked deliberately. It must **never be exposed casually
  in production**; productionizing it requires admin-only / dev-only gating (see go-live hardening below).

### Testing (Phase 1)
- **Engine/api selftest:** `scale_distribution` — `28×2 → {P1:22,P2:17,P3:9,P4:4,P5:4}` exact; `3×2 → 6`;
  `1×1 → 1`; and the **tiny-run edges**: `1×2 → 2` (total < #pillars: valid allocation, sums to 2, no crash,
  no negatives), plus a `posts_per_day × 7 < #formats` case. **Cursor integrity:** plan two consecutive
  arbitrary-size rounds and assert each pillar's cursor advanced by exactly the slots it was assigned
  (0-assignment pillars don't advance) and the second round resumes correctly. Generate-job lifecycle
  (start → poll → done, stub writer); `next_action` transitions (`RESERVED`→`generate`;
  generated→`start_review`; approved-no-script→`generate` at script; etc.); the two read-model bug fixes.
- **Playwright e2e:** New-run dialog → Generate topics (job + progress, `TANAGHOM_WRITER_STUB=1`) → review
  → Generate drafts → review; assert DB/API after each. Keep the 9 existing specs green.

---

## Phase 2 — serious UX/UI pass (separate design cycle, after Phase 1)

Done as its own brainstorm → design → plan cycle once Phase 1 gives a working surface to design against.

- **Use the frontend-design skill**, the visual companion (show mockups/options), `context7` for current
  library APIs, web research on comparable review/approval and pipeline tools, and available design tooling.
- **Use-case alignment:** a bilingual **AR (Palestinian) / EN** content review-and-approval pipeline
  ("git for content") for the Moataz Mashal brand. UI chrome English-only; content rendered bilingual with
  correct **RTL** handling. The reviewer's job is a stage-by-stage queue (Linear / GitHub-PR / inbox model):
  triage → decide → commit → advance, with reversible decisions and clear disposition.
- **Targets to evaluate in that cycle:** information hierarchy for a review queue, the stage rail / pipeline
  overview, density and scannability of cards, the bilingual/RTL content presentation, progress/generation
  affordances, empty/loading/error states, and the assistant panel's role. Output: a UX design doc +
  mockups, then an implementation plan.

---

## Risks / notes

- **HTTP-bound jobs in an in-process registry** are lost on API restart. Acceptable for a single-node dev
  tool; the DB-derived `done` count means a restart just loses the "running" flag, not the produced work.
- **Writer availability:** the API process must have `agents/requirements.txt` installed (it does). The
  generate endpoints 503 cleanly if not.
- **Bot singleton / shared DB** (parallel `feat/telegram-pilot` worktree) is unaffected; this work is on the
  main checkout and shared engine. Note the generation endpoints (above) are the shared mechanism the bot agent
  consumes after merge.

## Go-live / IAM hardening list (deferred — not Phase 1)

- **Reset (full wipe) must be admin-only / dev-only and never casually reachable in production.** Today:
  explicit confirmed operator action. Production: gate behind IAM (admin role), environment guard
  (refuse in prod unless an explicit dev/maintenance flag is set), and an audit entry for who ran it and when.
- **Shared-DB destructive actions** in general (reset, force-restore) need the same per-action confirmation +
  warning that they affect all sessions on the shared DB, and IAM gating when multi-user.
- **Generation endpoints** are unauthenticated in the dev tool; production needs auth + rate limits
  (LLM cost) and per-tenant scoping. Tracked here, built with M8/IAM.
