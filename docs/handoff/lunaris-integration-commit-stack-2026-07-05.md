# Lunaris Integration Commit Stack (2026-07-05)

The `feat/lunaris-redesign` WIP was converted into an auditable, per-concern local commit stack
(Strategy B). File-level staging only (never `git add .`/`-p`); mixed files flagged. **No push, no
GitHub/DB mutation.** WIP safety patch: `scratchpad/wip-tracked-2026-07-05b.patch` (faithful).

## Commit stack (on `feat/lunaris-redesign`, atop `efce9b8`)
| # | SHA | Message | Contents |
|---|-----|---------|----------|
| 1 | `f45eebc` | `chore: ignore lunaris local QA artifacts` | `.gitignore`: broaden `tmp/`, add `output/`, `.playwright-cli/`, `.pnpm-store/` |
| 2 | `051a09d` | `build: add lunaris integration foundation` | pnpm workspace/lockfile/deps, Next/Playwright config, pre-commit, `.env.example`, `i18n/*`, `.github/` (CODEOWNERS + PR template), `tools/` scripts |
| 3 | `103e3f0` | `feat: add CR01 review governance substrate` | `gates/{engine,api,directives,jobs}.py`, `loader/load_methodology.py`, `db/init/schema.sql`, `db/migrations/013–019`, `app/{admin,api/reviewer,gw}`, `components/admin`, `lib/reviewer-session.ts`, `planner/plan_round.py`, `system_config.example.yaml`, `.gitleaks.toml` (allowlist) |
| 4 | `5859ecc` | `feat: add lunaris review surface and #3 hardening` | `app/{layout,globals,fonts,icon}`, `components/review/*`, `lib/review-context.tsx`, `components/assistant/*`, `app/api/chat`, `agents/run_writers.py` |
| 5 | `0ce13c7` | `test: cover lunaris review and CR01 flows` | `dashboard/e2e/*` (10 specs + 3 seeds), `gates/{selftest,e2e_seed,api_selftest,e2e_final_seed,e2e_ops_seed,e2e_script_seed}.py` |
| 6 | *(this commit)* | `docs: record lunaris integration checkpoint` | all `docs/*`, root `*.md` (`HANDOFF`, `README`, `ROADMAP`, `BUILD_STATE`), design PNGs, + this handoff |

## Mixed files (file-level staging only — not hunk-splittable non-interactively)
| File | Commit | Why here / coupling |
|------|--------|---------------------|
| `gates/api.py` | 3 (CR01) | CR01 endpoints + `/gw` proxy + the **already-shipped #4** hunks (`ff33fba` on main). Dominant = CR01. |
| `planner/plan_round.py` | 3 (CR01) | CR01 `apply_managed_format_distribution` + the **already-shipped #4** empty-methodology guard. Dominant = planner. |
| `gates/api_selftest.py` | 5 (tests) | CR01/approval API tests + the **already-shipped #4** assertions. Dominant = tests. |
| `dashboard/lib/review-context.tsx` | 4 (Lunaris/#3) | **#3 hardening** (gwFetch, editChangeNote, orderedTargets, setStageKey guard) + CR01 (`/gw` base, reviewer-session) in one file. Dominant = #3/review-surface. |
> The #4 hunks in `api.py`/`plan_round.py`/`api_selftest.py` are identical to `main`'s (`ff33fba` is their
> ancestor); they will be a no-op on a later merge to `main`.

## `.github/` and `tools/` decision — COMMITTED (commit 2)
- `.github/`: `CODEOWNERS` + `pull_request_template.md` — repo governance, directly supports the release-gate
  workflow. Committed.
- `tools/`: dev/validation scripts (`check_design_sync.py` is referenced by `.pre-commit-config`;
  `dashboard-health-check.sh`, `codex-network-check.sh`, `reset_internal_baseline.py`,
  `build_program_evolution_report.py`, `start-penpot-mcp.sh`). Committed. `tools/__pycache__/` excluded (ignored).

## CR01 framing
CR01 (commit 3) is committed as a **named substrate stream** and is **required by** the Lunaris review surface
and #3: the `/gw` same-origin proxy, `reviewer-session` identity, `engine.decide … ON CONFLICT` (which the #3
edit-note fix depends on), approval/workflow governance, and migrations `013–019`. It has **no dedicated
close-path issue** yet — see STOP_REQUIRED below for issue/PR framing.

## #3 dependency framing
**#3 cannot ship independently of this branch.** Its correctness fixes (commit 4) are woven into the
Lunaris-redesigned surface and rely on the CR01 substrate (commit 3). `main` has neither, so #3 closes only
after this branch (carrying #3) is validated and integrated. `#24` (polish) stays separate; `#1` umbrella open.

## Validation
- **`py_compile` — ALL OK** (all 13 changed Python files: gates, planner, loader, agents).
- **`tsc --noEmit` (dashboard) — clean** (0 errors).
- **gitleaks — clean** on every commit (pre-commit hook). Two confirmed **false positives** were allowlisted
  in `.gitleaks.toml`: `default_kind` (a kwarg name) and `3sec_reel_caption` (a content-format key) — neither
  a real secret.
- Full-stack behavior (Playwright + API selftests with the stack running) is **not** run here — that's the
  separate validate directive (needs the app + DB up).

## Remaining uncommitted files
**None of the WIP.** After commit 6, the working tree has only ignored artifacts (`output/`, `tmp/`,
`.playwright-cli/`, `.pnpm-store/`, `__pycache__/`). No source/tests/docs remain uncommitted.

## Branch readiness
**Ready for validation.** The WIP is now a clean 6-commit stack; syntax/type checks pass; secrets clean.
Next is a full-stack validation pass (bring up gate API + dashboard, run Playwright + selftests), then
push + integration PR → `main`.

## Exact next directive
> **"Validate feat/lunaris-redesign integration stack: bring up the gate API (stub) + dashboard (prod build),
> run the full Playwright pack + `gates/api_selftest`/`selftest`; record results. If green, push
> `feat/lunaris-redesign` and open ONE integration PR → `main` (Lunaris + CR01 + #3). Do not close #3 until the
> PR merges."** Owner authorization required for the push/PR (and the CR01 issue/PR framing decision below).

## STOP_REQUIRED — owner decisions
1. **CR01 issue framing:** CR01 is a large substrate with no dedicated issue. Decide whether to (a) file a CR01
   integration issue for traceability, or (b) fold it into the Lunaris integration PR description. It ships
   with Lunaris/#3 regardless (entangled).
2. **Validation + push authorization:** authorize the full-stack validate directive, then the push + integration
   PR → `main`.
3. Confirm this branch's local commits (currently unpushed; `origin/feat/lunaris-redesign` is far behind at
   `6091d04`) should be pushed as-is once validated.
