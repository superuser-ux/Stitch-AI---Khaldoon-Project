# Lunaris Integration Validation (2026-07-05)

End-to-end validation of the committed `feat/lunaris-redesign` integration stack (Lunaris + CR01 + #3).
**Branch remained local-only. No push/PR/GitHub mutation. No DB cleanup.**

## Branch & commit stack (validated)
`feat/lunaris-redesign` @ `06e73ce` — clean tree. Stack: `f45eebc` (artifacts) · `051a09d` (build) ·
`103e3f0` (CR01 substrate) · `5859ecc` (Lunaris surface + #3) · `0ce13c7` (tests) · `06e73ce` (docs).
`origin/main` includes the #4 squash **`ff33fba`** ✓.

## Validation stack identity
- **Gate API:** `tanaghom-gateapi` on `:8009`, `TANAGHOM_WRITER_STUB=1`, mounts the integration checkout
  (`/Users/Kay/Dev/tanaghom` = this branch).
- **Dashboard:** freshly rebuilt (`npm run build` → ✓ compiled) + `next start :3000` (200).
- **DB:** shared **dev** `tanaghom-db` (pgvector) — **already CR01-migrated** (migrations `013–019` applied
  in prior WIP work; **no new migrations run this pass**). Validation used **sacrificial `RE2E` + auto test
  rounds** only (Playwright reseeds RE2E per run). **No client/demo data mutated; no cleanup/destructive SQL.**

## Commands run + results
| Check | Command | Result |
|-------|---------|--------|
| Backend static | `py_compile gates/api.py gates/engine.py planner/plan_round.py gates/api_selftest.py` | **OK** |
| TypeScript | `dashboard tsc --noEmit` | **clean (0 errors)** |
| Dashboard build | `npm run build` | **✓ compiled, 9/9 static pages** |
| Engine selftest | `python -m gates.selftest` | **ALL CHECKS PASSED** |
| API/CR01 selftest | `python -m gates.api_selftest` | **148 PASS / 0 FAIL — ALL API CHECKS PASSED** |
| Browser | `playwright test --project=chromium` | **37 passed / 0 failed (3.2m) — no flaky, no retries** |

## #3 behavior checklist (all green in the pack)
| #3 behavior | Evidence (passing spec) |
|-------------|-------------------------|
| Per-item review action consistency | `integrity-and-dispositions` "per-item actions apply immediately, dropped items restore cleanly" |
| Request-change **refinement** path | `review-iteration:121` "edit the change note on an awaiting item without undo" |
| Rework-from-older-version **warning/gate** | `review-iteration:152` "rework from an older version warns before discarding the newer head" |
| Regenerate/rework reliability through the redesigned surface | `review-iteration:40/75/103/183` (request-change → regenerate → re-enters, topic+script) |
| No card/bar/state drift | `review-iteration:57` "other cards stay actionable"; `integrity-and-dispositions:137` "actioned cards sink below still-pending (#3 ordering)" + "disposition summary updates live" |

## CR01 validation summary (substrate for Lunaris/#3)
CR01 is validated as the required substrate — **not** a separate issue this step:
- `api_selftest` (148/0) exercises approvals/workflow/reviewer identity/gates/agent hard-floor + the `/gw`
  reviewer-signed path.
- Browser specs covering CR01 flows all pass: `approval-visibility`, `production-chain-surface`,
  `final-stage-surface`, `script-stage-surface`, `schedule-and-topic-surface`, `content-handoff-flow`.

## #24 separation
No correctness/stability blocker surfaced. The previously-identified **#24** polish/legibility items
(disposition-summary completeness, approved-item vanish clarity, dropped-lane detail, progress telemetry,
auto-advance-when-done) remain **#24 follow-ups** and are **not** #3 closure blockers.

## Failures / blockers / fixes
- **None.** No validation failures; no application-source changes were needed. Backend + frontend + browser
  all green.

## gitleaks
Clean (pre-commit hook on every commit; two confirmed false positives `default_kind` / `3sec_reel_caption`
were allowlisted in `.gitleaks.toml` during the commit-stack step).

## Push/PR readiness verdict
**`READY_FOR_PUSH_PR`.** The integration stack is fully validated locally; `#3`'s behaviors are proven green
through the redesigned surface; CR01 substrate is green; branch is clean and local-only.

## Proposed integration PR (do NOT create yet — owner authorization required)
**Title:** `Lunaris review-surface redesign + CR01 governance substrate (closes #3)`
**Body:**
> ## Summary
> Integrates the Lunaris review-surface redesign, the CR01 review-governance substrate it depends on, and the
> #3 review-surface hardening built on top.
> - **CR01 substrate (required by Lunaris/#3):** approval/workflow governance, reviewer identity + `/gw` proxy,
>   `engine.decide … ON CONFLICT`, methodology loader/admin, migrations `013–019`.
> - **Lunaris surface:** redesigned review surface (Overview/Workflow lenses, RTL, theming) + #3 fixes
>   (funnel-resilient fetch, request-change refine-without-undo, rework-from-older discard warning,
>   regenerate/rework DB-truth convergence, card ordering).
> - **Tests:** review/CR01/generation e2e + API/engine selftests.
> ## Validation
> - `tsc` clean; `gates/selftest` ALL PASSED; `gates/api_selftest` 148 PASS / 0 FAIL; full Chromium
>   Playwright pack **37 passed / 0 failed** (no flaky/retries).
> - Fresh main-schema #4 guards already shipped (`ff33fba`); their hunks here are a no-op on merge.
> ## Issues
> Closes #3. CR01 ships as required substrate (documented here; no separate issue). #24 (polish) and #1
> (umbrella) stay open.

## Exact next owner authorization needed
1. **Authorize push** of `feat/lunaris-redesign` (currently `origin/feat/lunaris-redesign` is behind at
   `6091d04`) and **open the integration PR → `main`** with the title/body above.
2. **Merge method:** repo allows squash (a squash of a 6-commit integration is large; a **merge commit** may
   better preserve the per-concern commits — owner's call, subject to repo settings).
3. After merge: post #3 evidence + close #3; keep #24 and #1 open.
