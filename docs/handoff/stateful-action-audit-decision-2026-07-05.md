# Class-Level Stateful-Action Audit — Decision (#27)

Date: 2026-07-05
Author: CC (process-only audit; read-only, no GitHub/DB/code mutation)
Repo: `Kholio/tanaghom` · `origin/main` at audit time: `d3038aa`
Tracking issue: `#27 — Standing release-gate enforcement and class-level stateful-action audit` (P2, `type:process`)
Prompt: "Execute #27 Stateful-Action Audit Decision — CC only (OR)"

---

## Decision

**`DELIVER_AUDIT_ARTIFACT` → this document is the written class-level pass. Verdict: all 14 action classes are hardened in code with green test evidence; WAIVE further implementation. ONE optional, narrow test-depth follow-up is recommended (not required).**

Rationale: the audit did not find any *unprotected* stateful-action behavior. Every class has an implemented guard on `origin/main`, and the full Chromium pack (37/37) plus CR01 selftest (148/0) exercise them. The only residual is that a few concurrency guards (duplicate-click, overlapping-job, round-switch-mid-work, `/gw` timeout path) are protected in code but lack a *dedicated* regression test — a test-depth gap, not a correctness gap. Per the directive's "narrow follow-up rather than expanding #27 indefinitely," that residual is captured as one optional issue, not as a #27 blocker.

---

## 1. #27 acceptance matrix

| # | #27 acceptance | State | Evidence |
|---|----------------|-------|----------|
| 1 | Release-gate enforcement remains the active delivery rule | ✅ MET | `docs/16_Release_Gate_and_Delivery_Control.md` (active operating rule) + `.github/pull_request_template.md` (checkboxes) — applied through PRs #26/#28/#29 (one-file scopes, evidence in bodies, squash-merge with gate checks). |
| 2 | Class-level stateful-action audit delivered **or** explicitly waived with rationale | ✅ MET (this doc) | Written class-level pass below; verdict = covered + waive-further + one optional follow-up. |
| 3 | `status:*` label discipline for closed issues is defined | ✅ MET (defined in §4) | Proposal below; normalization of existing stale labels remains separate, per #27 scope. |

---

## 2. Stateful-action audit matrix

Legend — **C** = covered by #3/PR #26 with implemented guard **and** passing spec; **C‑w** = covered in code but weakly evidenced by a *dedicated* test (guard exists, no targeted regression test); **F** = not covered → follow-up; **N/A** = not applicable.

| # | Action class | Verdict | Implementation (on `main`) | Test evidence |
|---|--------------|---------|-----------------------------|---------------|
| 1 | Per-item approval | **C** | `decide("approve", [slot], _, "immediate")` via `run()` (global `busy`); `isCurrentStageContext` guard before state write (`review-context.tsx:579`,`565`) | `integrity-and-dispositions` "per-item actions apply immediately"; `approve-*` in 5 specs |
| 2 | Selective batch approval | **C** | `selectAllPending` + `selectedPending` + deferred `decide(…, "deferred")` staged, then `resolve()` commit with AI-advisory confirm (`disposition-bar.tsx:98–124`) | `integrity-and-dispositions` batch commit; explicit #3 acceptance "per-item and selective batch both behave" |
| 3 | Request-change | **C** | `decide("request_change", …, notes)` → `engine.decide` (`review-context.tsx:664`) | `request-*` in 3 specs; `co-creation` request→regenerate cycles |
| 4 | Regenerate | **C** | `regenerate()` DB-truth convergence (`reworkLanded()`/`stageReady`), gwFetch non-idempotent no-retry (`review-context.tsx:719–770`) | `review-iteration:40/75/103/183`, `co-creation` |
| 5 | Rework-from-version | **C** | `POST /rounds/{id}/rework?stage=` + linear restore chain; older-version path gated (below) | `co-creation` rework-from-earlier; `reworkfrom-*` in 2 specs; `approve-rev` |
| 6 | Drop / undo / restore | **C** | `decide("reject")` drop; pre-commit `undecide()` (`:629`); post-commit `restore()` → `resumeReviewIfNeeded` (`:634`) | drop/`reject-*` (4), `undo-*` (3: integrity, review-iteration, final-stage), `restore` (4) |
| 7 | Stage switching mid-work | **C** | `setStageKey` re-select no-op guard (#3 fix E, `:405`); stale-state effect keyed on stage/gate | `content-handoff-flow`, `co-creation` 2nd rework cycle |
| 8 | Round switching mid-work | **C** (race: C‑w) | `setRound` synchronously clears gate/stage/changes/dropped/selection + stamps `stageContextRef`; all async completions gated by `isCurrentStageContext` (`:386–404`,`:372`) | `round-trigger`/`round-opt` exercised in 9 specs; no *dedicated* switch-during-async-mutation race test |
| 9 | Duplicate-click protection | **C‑w** | Global `busy` via `run()` disables every mutating affordance (`actionBusy = busy \|\| reviewerSyncing` in disposition-bar/review-surface/review-item/stage-action) | Guard present + implicitly exercised; no *dedicated* double-click regression test |
| 10 | Overlapping-job protection | **C‑w** | `genJob` non-null disables generate (`stage-action.tsx:36`); regenerate through `busy`; DB-authoritative completion (#4 poll fix) | #4 full-pack green 30/30 ×2; no *dedicated* concurrent-job test |
| 11 | Background progress visibility | **C** (richness → #24) | `genJob {done,total,status,label}` + `refreshBurst` cascade | generation specs; progress *telemetry richness* is a #24 polish item, not correctness |
| 12 | Stale/older-version warning or discard gate | **C** | `confirmDiscard` gate on rework-from-older (head = `Math.max(revisions)`); `version-head` badge (#3 slice) | `review-iteration:152`, `co-creation` `reworkfrom-warning`/`reworkfrom-confirm`; `version-head` |
| 13 | Reviewer-session continuity | **C** | `reviewerSyncing` gates actions during identity sync; signed `x-principal-*` via `reviewer-session.ts` + `/gw` proxy | `api_selftest` 148/0 (reviewer-signed path, agent hard-floor); `approval-visibility` |
| 14 | `/gw` proxy under stranded request / timeout | **C‑w** (env) | `gwFetch` AbortController: GET 12s + 1 retry, writes 45s no-retry (funnel-starvation root fix, `:159–190`) | Live-validated on Tailscale funnel; inherently hard to e2e — no automated timeout-path test |

**Summary:** 10 × **C**, 4 × **C‑w** (rows 8-race, 9, 10, 14). **Zero F.** No unprotected behavior found.

---

## 3. Waiver / follow-up recommendation

- **Waive further implementation.** All classes are hardened; the acceptance obligation ("delivered or waived with rationale") is met by this artifact + verdict.
- **Optional single follow-up (recommended, not required):** dedicated regression tests for the four **C‑w** concurrency guards — duplicate-click, overlapping-job, round-switch-during-async-mutation, and (where feasible) a mocked `/gw` timeout/retry path. This deepens evidence without changing behavior. It is **test-depth**, explicitly **not** a correctness blocker, and does **not** hold #27 open on its own.
- **Do not** expand #27 into implementation work — no guard is missing.

---

## 4. Status-label discipline proposal (#27 acceptance 3)

**Rule:** a **closed** issue must not carry a non-terminal `status:*` label. On closure:
1. Remove any `status:in-validation` / `status:ready-to-close`.
2. Either apply a single terminal `status:done` label **or** carry no `status:*` label at all (the GitHub `CLOSED/COMPLETED` state is itself terminal). Recommendation: **carry no `status:*` on closed issues** — simplest, avoids a redundant label — and reserve `status:*` strictly for open work-in-flight.
3. Open issues use exactly one lifecycle `status:*` reflecting the release-gate delivery states (`Defined`→`In implementation`→`Ready for sacrificial validation`→`Demo-safe`→`Merge-ready`).

**Current violations (read-only observation; normalization is separate per #27 scope):** `#2` closed with `status:ready-to-close`, `#3` closed with `status:in-validation`, `#4` closed with `status:in-validation`. These are the concrete examples the discipline targets; fixing them is a separate authorized hygiene pass, not part of this decision.

---

## 5. Draft #27 comment (DO NOT POST without authorization)

> ## Class-level stateful-action audit — decision (2026-07-05)
>
> Delivered the written class-level pass (`docs/handoff/stateful-action-audit-decision-2026-07-05.md`). Verdict: **all 14 stateful-action classes are hardened on `main` with green test evidence** — 10 fully covered by #3/PR #26, 4 covered-in-code but with only a *dedicated-test* gap (duplicate-click, overlapping-job, round-switch-mid-work race, `/gw` timeout path). **Zero unprotected behaviors.**
>
> Key guards verified in code: global `busy`/`run()` disables every mutating affordance (duplicate-click); `genJob` disables generate (overlapping-job); `setRound` clears stage-scoped state + `isCurrentStageContext` gates all async writes (round/stage-switch races); `confirmDiscard`/`version-head` (rework-from-older); `gwFetch` timeout+bounded-retry (stranded `/gw`). Evidence: full Chromium pack 37/37, CR01 selftest 148/0.
>
> **Decision: the audit is delivered and further implementation is WAIVED** — no guard is missing. One **optional, narrow** follow-up is recommended (not required): dedicated regression tests for the four concurrency guards above. It is test-depth, not a correctness blocker, and does not hold #27 open.
>
> **Status-label discipline (acceptance 3) defined:** closed issues carry no non-terminal `status:*`; open issues carry exactly one lifecycle `status:*`. (Normalizing the existing stale labels on closed #2/#3/#4 remains a separate hygiene pass.)
>
> With the audit delivered, enforcement active, and label discipline defined, #27's three acceptance criteria are met. Recommend either closing #27 or keeping it open solely as the standing-enforcement tracker with the optional test-depth follow-up linked.

---

## 6. Draft follow-up issue (optional; DO NOT CREATE without authorization)

**Title:** Dedicated regression tests for review concurrency guards
**Labels:** `area:review-ui`, `type:test` (or `enhancement`), `priority:p3`
**Body:**

> Test-depth follow-up from the #27 stateful-action audit (2026-07-05). The guards below are implemented and behaving on `main`; this issue adds *dedicated* regression coverage so they can't silently regress. **Not a correctness blocker — no behavior change.**
>
> - **Duplicate-click**: assert a second click on a mutating affordance is a no-op while `busy` (double approve/resolve/regenerate emits one request).
> - **Overlapping-job**: assert `genJob` in-flight disables generate and a second generate cannot start.
> - **Round-switch-mid-work race**: switch rounds while a decide/regenerate is in flight; assert the completing request does not write into the new round's view (`isCurrentStageContext` guard).
> - **`/gw` timeout/retry** (if feasible with a mocked slow route): assert GET retries once at 12s and writes do not auto-retry at 45s.
>
> Scope: tests only. No product changes expected.

---

## 7. Exact next-owner authorization choices

Nothing below is executed; GitHub/DB/code untouched.

- **[A] Deliver + waive + close (recommended):** authorize posting the §5 comment on #27 and closing #27 completed (audit delivered, enforcement active, label discipline defined). *Optionally* also create the §6 test-depth follow-up first so the thread is linked before closing.
- **[B] Deliver + waive, keep #27 open:** post the §5 comment, create the §6 follow-up, keep #27 open purely as the standing-enforcement tracker.
- **[C] Deliver only, hold:** keep this artifact on file, post nothing, mutate nothing (current state).
- **[D] Persist this doc:** authorize a scoped docs PR (`docs: record stateful action audit decision`, one file) — this session left it **uncommitted** (on `main`, and "no push" applies), consistent with the #28 pattern of persisting via its own branch/PR.

Separately authorizable hygiene (non-blocking, per §4): normalize stale `status:*` labels on closed #2/#3/#4.

---

## 8. Process attestation

- Read-only: no GitHub mutation (no comment/close/label), no DB mutation, no code edits, no PR, no push, no commit.
- `#24` treated as separate/non-blocking throughout; no #24 work.
- Local Groq audit report **not** committed; `dashboard/.env.local` untouched; no secrets printed.
- No Pi usage; no R54/R55 or R2–R53 cleanup.
- Only action taken: read issues/PR/docs/code and authored this file (uncommitted).
