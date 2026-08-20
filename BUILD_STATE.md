# BUILD_STATE — read me first

> **2026-07-08 handover refresh:** for the current session snapshot (green baseline, merged PRs #105 and
> #107, planning-scan result #108, the directive-bus workflow, and do-not-touch items), read
> **[`HANDOFF.md`](HANDOFF.md)** first — it is the up-to-date resume brief. This file remains the milestone
> tracker and retained historical record below; if older next-step notes here conflict with `HANDOFF.md`,
> follow the refreshed handoff.

**Purpose:** continuity across coding agents/sessions. Any agent (Claude Code, Codex, other) reads this file FIRST, does the next unchecked task, updates this file, and commits. If a session resets or hits a limit, the next one resumes here with zero lost context.

## Project
Tanaghom autonomous content dept — Phase 1 (Strategy → Topic → Script + approvals).
Hosting: local Windows workstation (RTX 3090), Docker Desktop (WSL2).

## Source-of-truth documents (in this folder)
- `docs/00_INDEX.md` — top-level documentation index.
- `docs/14_Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.md` — canonical change request and release-readiness report for the current repository worktree; client `.docx` / `.pdf` deliverables live in `output/doc/`.
  - Shared client/internal reference baseline: issue `1.2` dated `July 2, 2026` unless and until a newer issue is formally published.
- `Tanaghom_Content_Dept_Blueprint_v2.md` — architecture + decisions
- `Phase1_Build_Spec_v1.md` — what to build (DDL, agents, gates, acceptance)
- `HCS_Records_All42_Seed_v1.md` — methodology data (42 records)
- `Voice_Performance_Calibration_v1.md` — voice + format/length rules
- `system_config.example.yaml` — all tunable parameters (copy to `system_config.yaml`)
- `docker-compose.yml` — local stack

## Conventions
- Keep ALL behavior tunable via `system_config.yaml` (no hardcoded params).
- Every stage gated; nothing publishes without human approval; log every transition.
- Tool-agnostic: no dependency on a specific coding assistant.

## Milestones (update status as you go)
- [x] **M1 Foundation** — docker stack up; Postgres+pgvector; schema loaded (14 tables); 42 HCS + canon seeded; data visible in Adminer.
- [x] **M2 Planner** — generate a 28-day round (correct pillar/format mix, HCS cursor, lens rotation, no repeats).
- [x] **M3 Writers** — Topic + Script agents wired to canon + config; hard self-checks; dedup net.
- [x] **M3 round complete** — full **56-slot R1 round** generated end-to-end on **Groq** (Llama 4 Scout primary, Qwen3-32B fallback); voice signed off by Khal. All 56 slots **DRAFT_ASSIGNED**; 5-pillar full-script sample in `samples/round1_preview.md`.
- [x] **M4 Gates + surfaces** — engine + dashboard + Telegram, all config-driven + audited. M4.1 BLOCKS 1–3 (two-stage review, config hygiene, foundations). Proven by `gates/selftest.py`.
- [~] **M5 Polish + dry run** — reviews built as **suggest→dispose (escalate/waive) sign-off gates**, config-driven policy, proven; full live dry run HELD for the clean Scout round (after Groq daily reset) — to do together.
- [~] **M9 v1-lifecycle completion** (Track A, branch `track-a/m9`) — **B1 + B2 + B3 done** (directive+stage contract; manual gates + DAM + integration seams; Unified Actor Model autonomy + finished-media re-escalation). Remaining Phase-A items to follow.

## Current status
- Current resume state: **see [`HANDOFF.md`](HANDOFF.md)**. It now reflects the post-#105 / post-#107
  merged state and the post-#108 planning posture.
- Historical milestone state: **Phase 1 (UI-driven runs) remains the foundational build milestone on
  `feat/ui-driven-runs`, with later directive-bus slices merged on `main`.**
- Last refreshed by: _Codex / 2026-07-08 (docs refresh after #105, #107, and #108)_
- Next action (needs human): choose the next implementation directive from fresh backlog inspection after
  this docs refresh. Do not treat the older Phase-2 / reset note here as the active queue without
  re-checking `HANDOFF.md` and live GitHub state.

### Continuity note — R1 Stage 4 closeout (V2 final-review vertical), 2026-08-11
- **Two distinct SHAs — do not conflate them.** **Parent/base exact main SHA**
  `ee3676975b30db7808a69dc84f50288b72790c3b` (== `origin/main` at the time) is the state the defect was
  **reproduced on, before any edit**. The **final closeout exact HEAD** is **this commit** on
  `fix/r1-stage4-closeout` — parent = that base SHA — carrying the source fix, the added test and these
  docs; its hash is recorded in the closeout report, since a commit cannot contain its own hash.
  Post-fix validation, runtime identity and browser evidence were captured against the **final closeout
  HEAD** tree. Source-only slice — **no deployment, no schema, no backend change.**
- **Stage-4 V2 truth is now written down** in `docs/final-review-read-projection.md` (new section
  *"Stage 4 in V2 — the operator vertical over this contract"*), not left to be inferred from the UI.
  Canonical order: **inspect** (read-only) → **decision** (CANONICAL APPROVAL AUTHORITY, taken through
  the gate) → **sign-off** (IMMUTABLE EVIDENCE ONLY — an attributable receipt that approves nothing,
  advances nothing, and never substitutes for the decision) → **resolve** (LIFECYCLE AUTHORITY, the only
  mover). Four separate explicit gestures; none triggers another.
- **Advancement is MANUAL** — current governed behaviour of this workflow, *not* a platform invariant.
  An **automatic-advance option is not implemented** (not disabled, not pending rollout).
- **Read models are NOT authoritative.** The final-review projections are evidence for a human to read;
  authority stays in the gate and the lifecycle stays in resolve. Reachability is **derived** from the
  governed workflow artifact (`IMPLEMENTED_GATES` only ever narrows it); `final_review` is not asserted
  as a universal workflow assumption. Targets/sources are bound **exactly** (immutable attached package).
- **Protected scope:** **#442 untouched**; **Stage 5 only after Stage 4 is accepted and merged.**
- **Closeout defect — found, reproduced, corrected:** a **pre-existing 375px Workbench shell-header
  overflow** in the SHARED shell (not in Final Review). Reproduced at exact head *before* any edit:
  **+223 px** document overflow at 375×812 with the control cluster at **585.8 px** — identical at 375,
  768 and 1280 — and `agent-trigger` / `process-studio-link` / `secrets-admin-link` off-screen. The
  repo's own red control (`workbench/e2e/shell-containment.spec.ts:68`) was **already failing at head**
  with the same `223`. Cause: `flex-wrap` together with `shrink-0`, which pins the box at max-content so
  the wrap can never engage. Fix is presentation-only: `shrink-0` → `min-w-0` (+ `justify-end`).
  After: **0 px** overflow at 375, cluster **351 × 64.3** (wrapped to two rows), nothing off-screen;
  tablet/desktop **unchanged**.
- **Validation (all at the exact head SHA, serial, `workers:1`, `retries:0`, zero retries used):**
  `tsc --noEmit` clean · `next build` clean · focused shell pack **17/17 passed** (real exit 0) ·
  new red control proven **fail-before (223) / pass-after** · Orca embedded-browser evidence at
  **375 / tablet / desktop** against the dedicated exact-head runtime: **0 px** overflow and **zero**
  header controls off-screen at all three, with the cluster wrapped at 375 and unchanged at
  tablet/desktop. All evidence comes from a workbench **built from this worktree** whose identity was
  read from `/api/runtime`; **nothing is sourced from the pre-existing `:3001` reviewer lane**, which
  serves a different worktree at a divergent SHA and is recorded only as the trap that was avoided.
- **Whole-suite movement (`--project=product-regression`, same lane, adjacent runs):** **67 failed / 199
  passed → 55 failed / 212 passed**; **13 tests fixed across 9 spec files, every one a 375px
  horizontal-overflow assertion**, and **zero new failures** attributable to the change.
- **Known pre-existing failures, NOT caused by this change (tracked, still red):** the remaining 55 are
  environmental/fixture-lane, chiefly `run-schedule` (16), `calendar-geometry` (12), `schedule-views` (5),
  `scripts-lane-355` (4); plus **3 `brand-continuity` V1 tests that require the V1 dashboard on `:3000`,
  which is not running in this lane** (and this branch changes **zero** files under `dashboard/`), and
  `coexistence` (3) which likewise drives V1. A further **45 "did not run"** are downstream of failing
  setup in those same specs. This count is identical in kind to the baseline.

### Continuity note — CR01 approval/workflow track, 2026-07-02
- **Controlled Claude Code handoff is now viable as of July 4, 2026.** Use `HANDOFF.md` as the operating brief and keep Claude Code on one GitHub issue at a time. Do not let it run broad unsliced improvement passes in this repo.
- **Historical recommended execution order for Claude Code:** `#3` review-surface hardening -> `#12` stale summary after resolve if still blocking -> `#7` calendar/numbering/content-type alignment -> `#6` workflow governance/admin hardening -> `#5` operational green preflight -> `#8` Telegram in its own worktree. This is retained history, not the current post-#105 / post-#107 directive queue.
- **Validation evidence improved further on 2026-07-04:** `#9` approval semantics slice is browser-green after surfacing remaining required approvers on pending cards; `#4` planner/content-type drift is covered by both API and browser regression; `#2` sacrificial live rework validation now includes a real script-semantic tightening in `agents/run_writers.py` after the first live script rework under-applied a reviewer note. The remaining gap on `#2` is interruption/resume simulation, not core semantic responsiveness.
- **`Full reset mode` now has a fixed meaning for this repo:** wipe run-derived operational data only (`round`, `slot`, `topic`, `script`, review/approval/gate/directive/asset tables, `lens_history`, `hcs_cursor`, run-linked audit rows), preserve foundational/admin catalogues (`methodology*`, `workflow*`, `content_format*`, `format`, principals/roles/groups), and leave the system with zero seeded runs so a fresh demo can start from empty.
- **Release-control baseline is now formalized:** `docs/16_Release_Gate_and_Delivery_Control.md` defines the active repo rule for scope control, validation order, demo-safe readiness, and GitHub issue discipline. Future implementation should route through that process instead of mixed-scope incremental landing.
- **Canonical readiness artifact published:** `docs/14_Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.md` now serves as the repository's canonical change request / release-readiness source report for the current worktree, with client deliverables generated into `output/doc/`.
- **Shared document baseline fixed for continuity:** current common reference with the client is **issue 1.2 dated July 2, 2026**. Internal documentation updates that touch release status, companion-system readiness, screenshots, or change-request wording must stay aligned to that same issue until superseded.
- **Client-facing edition enriched:** the current issue now uses client-friendly language, verified companion-system status for Analytics / SDAM / AVP, explicit note that the official Moataz analytics account path is intentionally deferred, and a screenshot / placeholder appendix for direct distribution.
- **Client `.docx` reconciled back into tracked support files:** embedded screenshots from the current client artifact were extracted into `docs/assets/program_evolution_report_v1_0/`, and the tracked report source / continuity docs now point to the same visual set and wording so internal and client-facing references stay aligned on one version line.
- **Change Request 01 is in active implementation in this worktree.** Core identity/assignment groundwork, DB-backed approval policies, pending-approval queries, workflow version schema/backend, and the admin workflow surface are now present locally alongside the existing Phase-1 stack.
- **Operational UI slice advanced materially:** the overview now exposes per-user pending approvals, matched assignment paths, and required approvers; the inbox stage shows a reviewer-facing **Your approval context** panel for the active approval gate; review cards surface approval progress.
- **P6 foundation added:** new versioned methodology tables plus content-format/platform registry tables were added (`017_cr01_methodology_formats.sql`), the markdown loader now seeds them idempotently, and the new read-only admin surface lives at `/admin/methodology`.
- **Live browser verification was completed after a real dashboard rebuild/restart.** A stale `next start` process caused a `ChunkLoadError` and partial client rendering; `pnpm build` + restarting `next start` on `:3000` resolved it.
- **CR01 navigation bug fixed:** opening a pending approval from the overview now switches both the stage and the owning round (for example `RE2E`), so the user lands on the correct review surface instead of staying on the previously selected plan.
- **Current verified status:** engine compile ok, `gates.api_selftest` passes, dashboard `next build` passes, `/admin/methodology` browser smoke-check passes, browser flow verified on the rebuilt app.
- **GitHub tracking gap closed:** approval governance is now split more cleanly into issue `#9` (server-resolved approval identity and assignment authorization) and issue `#10` (`ANY`/`ALL` semantics, assignment snapshots, and audit closure), alongside existing stabilization and UX issues.
- **Approval identity path tightened further on 2026-07-04:** sensitive review/approval actions now require a signed trusted principal at the API boundary instead of accepting request-body actor/approver fields as authority. The live proof now explicitly passes unsigned-caller rejection (`401`) and signed-mismatch rejection (`400`) while the dashboard path remains green through the `/gw` reviewer proxy. Validation: `gates.api_selftest`, `dashboard` `tsc --noEmit`, and Playwright `schedule-and-topic-surface` + `script-stage-surface`.
- **New feature stream captured cleanly:** issue `#11` now tracks the separate `agent-first cowork surface` request so it does not get mixed into the current stabilization or CR01 completion streams. Internal reference note: `docs/17_Agent_First_Cowork_Surface_Feature_Request.md`.

### Continuity note — Penpot MCP environment, 2026-07-03
- **Canonical Penpot MCP runbook added:** `docs/design/PENPOT_MCP_LOCAL_SETUP.md` is now the tracked source for the self-hosted Penpot + local MCP environment used for UI/UX design work.
- **Deployment shape recorded:** Penpot itself is running separately in Docker on this Mac at `http://localhost:9001`, while the MCP/plugin runtime is a host-side Node process that serves:
  - plugin manifest on `http://localhost:4400/manifest.json`
  - MCP HTTP on `http://localhost:4401/mcp`
  - plugin WebSocket bridge on `ws://localhost:4402`
  - REPL helper on `http://localhost:4403`
- **Machine-specific fixes recorded:** the active Hermes-managed Node install initially lacked `corepack` on `PATH`. Also, the published npm `@penpot/mcp@stable` package was only `2.15.4`, which produced a Penpot-side version mismatch against local Penpot `2.16.2`. The working fix was to use the official Penpot source tag `2.16.2`, run `mcp/scripts/set-version`, and build the MCP runtime from `/Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp`.
- **Build-policy note:** for the `2.16.2` source build, `pnpm.onlyBuiltDependencies` had to include `esbuild` and `sharp`, then `corepack pnpm rebuild` was run before `corepack pnpm run build`.
- **Repo-owned launcher added:** `/Users/Kay/Dev/tanaghom/tools/start-penpot-mcp.sh` now encapsulates the aligned `2.16.2` startup path and should be the default entry point for future sessions.
- **Important readiness distinction:** host-side MCP servers were verified listening and protocol-healthy on 2026-07-03, and a real plugin WebSocket handshake was observed on the aligned `2.16.2` runtime. Future agents must still ensure the Penpot plugin panel remains open and shows `Connected` during actual MCP use.

### Continuity note — Penpot reboot recovery, 2026-07-04
- **Post-restart failure mode reproduced and fixed:** after a system restart, Penpot returned `502 Bad Gateway` in the in-app browser even though all Penpot compose containers were `Up`.
- **Confirmed root cause on this Mac:** the frontend nginx process had cached an old backend container IP (`172.26.0.4:6060`) after backend recreation, while the live backend had moved to a new Docker IP. Also, backend and exporter now require the same explicit `PENPOT_SECRET_KEY` in `/Users/Kay/penpot_compose/docker-compose.yaml` to avoid restart instability.
- **Confirmed recovery path:** `docker compose up -d` in `/Users/Kay/penpot_compose`, then `docker compose restart penpot-frontend`, then verify `curl -sS -D - http://localhost:9001/api/main/methods/get-profile` returns `200 OK`.
- **Current live state after recovery:** Penpot login renders again in the in-app browser at `http://localhost:9001/#/auth/login`; host-side MCP manifest and HTTP transport are healthy (`4400` manifest `200`, `4401/mcp` returns protocol-expected `406`).

### Continuity note — current working branch / local design state, 2026-07-01
- **Current branch in this worktree = `feat/lunaris-redesign`** (off `main`). It extends the dashboard with the lunaris shell/lenses (Overview / Workflow / Grid / Calendar) and is **green again** after fixing a frontend async race in `dashboard/lib/review-context.tsx`: creating a new run could let an older round/stage fetch overwrite the fresh selection, which broke `dashboard/e2e/runs-and-generation.spec.ts`. Fixed by routing new-run through the guarded round switch and ignoring stale `load()` responses. Rebuilt + re-verified: **Playwright 10/10**.
- **Pencil/local-only work exists beyond git.** The local `~/.pencil/.../pencil-lunaris.pen` includes the tracked boards plus a large `lunaris: design system components` board and exploratory `dashboard-utility` / `dashboard-revenue` / `dashboard-football` studies. These are **not portable via git** unless explicitly exported.
- **Design-source sync:** the local Pencil **`v2 — Agentic Content OS (vision)`** and **`Workflow Graph`** boards are now aligned to the corrected platform model (Instagram publish target; Telegram control channel), and the portable exports were refreshed into `docs/design/lunaris/01-overview.png`, `02-workflow.png`, and `04-vision-agentic-os.png`. Extra local-only boards still remain local unless explicitly exported.
- **Sync guard added:** managed Lunaris continuity is now formalized via `docs/design/lunaris/SYNC_POLICY.md`, `sync-map.json`, `sync-status.json`, and the pre-commit hook `tools/check_design_sync.py`. Commits touching managed dashboard design surfaces or managed exports must include a refreshed `sync-status.json`.

### Phase 1 — UI-driven runs + generation jobs, 2026-06-30  (branch `feat/ui-driven-runs`)
Spec `docs/superpowers/specs/2026-06-30-ui-driven-runs-design.md`; plan `docs/superpowers/plans/2026-06-30-ui-driven-runs-phase1.md`.
- **Start a run from the UI:** `POST /rounds {days, posts_per_day}` (default 28×2, open range). Planner now scales the pillar/format mix as RATIOS (largest-remainder) so any size works; **28×2 reproduces the exact 22/17/9/4/4 = 56**. Tiny-run (total < #pillars) degrades gracefully; cursor integrity holds. New-run dialog in the topbar.
- **Generation is UI-driven (single mechanism):** `POST /rounds/{id}/stages/{stage}/generate` starts a background job (in-process daemon thread — extends the rework pattern; durable queue is if-scale, NOT built); `GET /jobs/{id}` returns DB-derived progress. The Telegram agent will consume the SAME endpoints (no parallel path). Config-driven via `generator`/`generates_from`/`writer_mode` on the topic_review + script_review gates.
- **One action surface for all 8 stages:** `stage_state.next_action` (generate|start_review|reviewing|ready_to_commit|awaiting_regeneration|complete|empty) drives a single `StageAction` component. **Bug fixes:** the script stage no longer falsely reads "complete" when topics are approved but scripts aren't generated yet (it says "generate"); `complete` now requires something actually advanced (no inherited-`dropped` bleed). Misleading "Start the review to load…" copy replaced.
- **Suites:** engine `selftest.py` (+job registry, +next_action), API `api_selftest.py` (+planner scaling, +POST /rounds, +generation-job, cursor integrity), lifecycle, Playwright e2e (new `runs-and-generation.spec.ts`; 10/10). All green.
- **Reset:** NOT yet done — it's a coordinated, destructive shared-DB wipe (clears the telegram session's data too). Awaiting human go-ahead.

### Security remediation, 2026-06-30  (branch `feat/ui-driven-runs`)
A live GROQ key + the Postgres password were committed in plaintext in the Phase-1 plan doc (Task 9 runbook). Fixed:
- **Scrubbed** the plan doc to `--env-file .env`; whole-repo grep clean; `.env`/`system_config.yaml` confirmed gitignored.
- **Purged from history** via `git filter-branch` over the 4 local (unpushed) commits + dropped backup refs + reflog + gc → old commits unreachable, 0 secret blobs; gitleaks history scan clean.
- **Rotated the Postgres password** (`ALTER ROLE`, both gitignored `.env`s, gateapi recreated via `--env-file`).
- **Pre-commit secret scan:** `.pre-commit-config.yaml` + `.gitleaks.toml` (committed) + an active `gitleaks protect --staged` hook.
- **STILL NEEDS YOU:** rotate the **GROQ API key** in the Groq console (I can't) and update `.env`.

### Go-live / IAM hardening (deferred — added this pass)
- **Local Postgres uses `trust` auth** — the password is NOT enforced over TCP (pgvector image default). Real protection needs `POSTGRES_HOST_AUTH_METHOD=scram-sha-256` + `pg_hba`. Not changed (would break the local stack + parallel session); do at go-live.
- **Reset (full wipe)** must be admin/dev-only + env-guarded in production; **generation endpoints** need auth + rate limits + per-tenant scoping (M8/IAM).

### Gate hygiene — one open review per round+stage, 2026-06-30  (migration 012, branch `main`)
Closes the FLOW FINDING from the flow-validation pass: duplicate/stale open gates can no longer make a stage look like it's `reviewing`.
- **`open_gate` is now IDEMPOTENT** (round-scoped opens only): if an active open gate already exists for a round+stage it is REUSED — no second gate, no wrong-stage class. Slot-scoped opens (version navigation) still create fresh gates, untouched.
- **`stage_state` ignores ORPHAN/stale gates:** it reads the *active* open review via the new `_active_open_gate()` helper — the oldest open gate that still has a target at the stage's review status. Orphans (all targets advanced) and accidental duplicates are auto-**superseded** (new `gate_status = 'superseded'`, migration 012) and audited (`gate_superseded` / `gate_reused`). A leftover gate whose items already advanced never reports `reviewing` again.
- **Dashboard:** `load()` binds the gate via `stage_state.gate_id` (never an orphan); removed the now-redundant `loadStageState` effect.
- **Regression-protected:** `gates/api_selftest.py` §0 (isolated round RIDEM) — open twice → ONE gate; advance targets via a slot-scoped gate → `stage_state` is not `reviewing` + the orphan is auto-superseded. All 4 suites green (engine · API · lifecycle · Playwright e2e ×9).

### Flow validation — R3 driven to SCHEDULED, 2026-06-30  (Mode: validate PROCESS + FLOW; quality deprioritized)
Drove R3's batch through every stage on the live API: `scripts → script_review → final_review (escalate + waive + scholar sign-off) → production (placeholder DAM raw-cut) → media_edit (placeholder DAM edit) → distribution → SCHEDULED`. **All FLOW checks passed** — at each step the handoff directive emitted with the right inputs + acceptance_criteria, the gate opened/resolved, the manual stage accepted the DAM asset, the commit checkpoint advanced approved items, and reversible reject→Dropped→restore behaved. R3 = **5 SCHEDULED**.
- **FLOW FINDING (to fix; the shallow kind expected):** `open_gate` does NOT dedupe — two surfaces (UI "Start review" + the API driver) created **two open gates** for the same round+stage. And `stage_state` reports `reviewing` whenever *any* open gate exists, even a STALE/orphan one whose targets have already advanced (it showed `reviewing` for a leftover `script_review` gate after the items reached SCHEDULED). **Fix options:** `open_gate` returns the existing open gate for a round+stage instead of creating a duplicate; and/or `stage_state` ignores an open gate whose targets are no longer at the stage's `reviews_status`. (Cleaned the orphan gate manually for now; R3 stage states are correct.)
- **QUALITY observations logged** (NOT fixed — parallel track) in `docs/QUALITY_BACKLOG.md`: R3-D02-PM script `script_hard_fail` (Egyptian «كده») + missing metaphor; R3-D01-PM `dialect_soft_warn`; native-review-discretion coverage note.
- **Regression-protected:** new `gates/lifecycle_selftest.py` drives an isolated round (RLIFE) `scripts→…→SCHEDULED` (stub writer) asserting the directive handoff chain (script→production→media_edit→distribution), the manual-stage DAM, the escalate/waive + sign-off, and quorum-all final review. **PASSES.** Suites now: engine `selftest.py` · API `api_selftest.py` · lifecycle `lifecycle_selftest.py` · Playwright `e2e/*` — all green.

### Batch-commit checkpoint + AI advisory + graceful stage states, 2026-06-30  (branch `feat/review-surface`)
Closes the heart-flow. Engine = single source of truth; all 3 suites green.
- **No scary errors on normal conditions.** New `engine.stage_state(round, stage)` read model → state ∈ {ready_to_start, reviewing, ready_to_commit, awaiting_regeneration, complete, empty}. The surface renders a contextual state (e.g. "Review complete — N advanced, M dropped (recoverable)") instead of throwing "no slots". API `GET /rounds/{id}/stages/{stage}/state`.
- **Explicit, human-confirmed batch-commit (= the engine's `resolve`, relabeled "Commit batch → advance").** Advances APPROVED items (output directive emits), parks dropped (recoverable), audited checkpoint. **AI advisory** (recommendation + warnings: items-still-pending-will-be-excluded, coverage-gap-from-drops, nothing-advances). Risky commits (pending / coverage gap) require an extra in-UI confirm; clean ones are one click. The advisory is computed locally in the bar (lag-free) AND server-side in `stage_state` (for the assistant).
- **Hard-floor human gate.** The assistant proactively RECOMMENDS committing when ready + WARNS, but `submit_decisions` only fires on explicit human ask — never auto-commit (Unified Actor Model). Reusable `DispositionBar` across all 8 stages.
- **Tests:** api_selftest (+ ready_to_commit advisory, + restored-item → ready_to_start = no error). Playwright now **9 specs** (+ nothing-pending → contextual state not error, + commit advances + emits handoff, + committing-with-pending warns & needs confirmation). ARCHITECTURE.md "Git for content" extended with the commit checkpoint + AI-advisory model.

### Reversible reject — "git for content", 2026-06-30  (migration 011, branch `feat/review-surface`)
Reject is now REVERSIBLE, not destructive — extends the event-sourced frame (see ARCHITECTURE.md "Git for content"). Nothing is ever deleted; the current state is a movable pointer over append-only events.
- **`REJECTED` (reversible 'dropped') state** (migration 011; config `gates.<stage>.reject_to`): on submit, reject → `REJECTED` — excluded from the active batch/review/regeneration + NOT approvable (integrity guard now covers `parked_statuses` = changes ∪ reject), but **recoverable**. Distinct from request-change (→ CHANGES_REQUESTED → regenerate); no overlap.
- **Reversals (engine + API, all audited):** `reopen` (un-reject a dropped item / un-approve a committed one → back to its review status, clears the approved pin); `clear_decision` (pre-commit undo → pending). API: `POST /slots/{id}/reopen`, `POST /gates/{id}/undecide`, `GET /rounds/{id}/dropped`. `list_rounds` now returns reserved/changes_requested/rejected counts + a derived `phase` (planned/in-review/awaiting-regeneration/approved/scheduled/dropped/active).
- **UI:** reject button = **"Drop (recoverable)"**; decided items get an **Undo** (pre-commit); a **"Dropped — recoverable (N)"** panel with **Restore**; a persistent **round-status** line (phase + iteration stats). Assistant: round status + dropped in context + a `reopen_slot` tool (answers "status of R<n>?", "restore the dropped X").
- **Tests (all 3 green):** engine `selftest.py`; api `api_selftest.py` (+reject→REJECTED→dropped→reopen→active, un-approve, history preserved); Playwright **6 specs** (+reject is a recoverable drop/restore, +pre-commit Undo & post-commit un-approve = batch checkpoint). ARCHITECTURE.md records the model.

### PHASE 2 — ONE canonical review surface (rebuild), 2026-06-30  (branch `feat/review-surface`, off `main`)
Engine untouched (single source of truth). Reused the existing `data-testid`s so the Playwright suite stayed green; added E2E for the integrity guard, reject path, and disposition summary.
- **Admin shell** (`components/review/app-shell.tsx`): shadcn sidebar = the 8 stages grouped (Content / Sign-off / Production); topbar = plan + reviewer selectors + an assistant toggle; slide-in assistant drawer.
- **Reusable `ReviewSurface`** (+ `ReviewItem`, `DispositionBar`) — ONE component every stage inherits (`lib/review-context.tsx` holds the state/engine calls; components consume it). Inbox/PR-review feel: disposition bar → awaiting-regeneration lane → per-item review feed.
- **Fixed resolve UX:** per-item decisions with immediate feedback (each card shows its recorded decision); a **live disposition summary** (`N in review · X approved · Y sent back · Z rejected · W pending`); one primary commit — **"Submit decisions"**. **Business lexicon — removed all "gate"/"resolve"/"quorum" wording** ("Start review", "Submit decisions", "Send back for changes").
- **assistant-ui replaces CopilotKit** (`components/assistant/assistant-panel.tsx` + `app/api/chat/route.ts`): a THIN chat — custom `ChatModelAdapter` (assistant-ui primitives, no vendor chrome) → `/api/chat` → Groq with tools (`decide_on_slot`, `submit_decisions`) that drive the SAME gate engine (audited). CopilotKit deps + `/api/copilotkit` removed. Smoke-tested live (reads the queue, answers correctly).
- **Tests (all 3 green):** engine `gates/selftest.py`, API `gates/api_selftest.py`, Playwright `dashboard/e2e/*` — now **4 specs**: the co-creation+version-nav flow (unchanged, green on the new surface) + **reject loops back (distinct from sent-back)** + **integrity guard (a sent-back item can't be approved; API refuses re-pull 400)** + **live disposition summary**. Per-test reseed via `docker exec tanaghom-gateapi python gates/e2e_seed.py` (fast). Run E2E with gate API `TANAGHOM_WRITER_STUB=1`.

### PHASE 1 — Playwright UI/logic audit, 2026-06-30  (branch `track-a/m9`)
Behavior ground-truth, **independent of UI clarity**: Playwright drives the REAL dashboard (real clicks) and asserts DB/API after each action — complements `api_selftest.py` (which bypasses the UI). **Suite green (7 steps).**
- **Files:** `dashboard/playwright.config.ts`, `dashboard/e2e/global-setup.ts` (reseeds an isolated round via the engine), `dashboard/e2e/co-creation.spec.ts`; `gates/e2e_seed.py` (seeds/opens RE2E). Stable `data-testid` hooks added across the dashboard (round selector, cards, decide/resolve/regenerate, version-history + per-version actions) — carry into the Phase-2 rebuild.
- **Determinism:** the gate API runs with `TANAGHOM_WRITER_STUB=1` during E2E (the env-gated deterministic, comment-responsive stub writer); flip it off for the real walkthrough.
- **Asserted end-to-end through the UI:** request-change → **CHANGES_REQUESTED** (excluded from the queue, shown in the awaiting-regeneration panel, not approvable) → **Regenerate → v2** (reflects the comment) → cycle again → **v3 reflects the SECOND comment**, history chains v1→v2→v3 linearly → **Rework-from v1** → restore (v4 = copy of v1) + rework (v5), full history preserved → **Approve a NON-latest version (v2 while v5 is head)** → the topic→script directive carries v2. Run: gate API with `TANAGHOM_WRITER_STUB=1` + dashboard up, then `cd dashboard && pnpm exec playwright test`.

### M9 — cyclic co-creation + LINEAR version navigation, 2026-06-30  (migration 010, branch `track-a/m9`)
Builds on the loop-close fix. Revisions are **append-only & immutable**; navigation is **linear (no version tree)**.
- **Cyclic (confirmed + tested):** rework increments revision each cycle (v1→v2→v3…) and injects the **LATEST** change-request comment (`select_rework` DISTINCT-ON newest); each revision stores its own comment + change-summary + `base_revision` provenance (migration 010). No one-shot limit; the UI signals the revision count.
- **Approved-revision pointer:** `decide` takes an optional `revision` (approve v2 even if v3 exists); on approval `resolve` pins `slot_approval(slot, artifact, revision)`. The **downstream directive carries that exact revision** — `directives.emit_output` + `process_script` read the APPROVED revision, not the head. Audited (`approved_revision`).
- **Restore / rework-from vN (linear):** `engine.restore_revision` appends a NEW head COPIED from vN (provenance `base_revision=vN`), clears the approved pointer, and returns the slot for re-review — no branch. `run_writers.rework_one` regenerates a single slot from its head with a comment. API: `POST /slots/{id}/restore`, `POST /slots/{id}/rework_from {artifact,revision,comment}` (restore + rework, background), `GET /slots/{id}/revisions`.
- **UI (version history):** the history toggle shows the full linear chain — per version: the comment, the change-summary, `based on vN` provenance, an "approved" marker, and **two actions — "Approve this version" (pins that revision) and "Rework from this version (with a comment)"**.
- **Tests (`gates/api_selftest.py`, live API + stub writer):** (1) two cycles v2→v3 — v3 reflects the SECOND comment, history chains v1→v2→v3 with linear base_revision; (2) approve a NON-latest revision → the topic→script directive carries that revision (v2 while v3 exists); (3) restore-from-v1 → v4 copied from v1 (`based on v1`) → rework → v5 derived from v4, full history (v1..v5) preserved. **Both suites PASS.**

### M9 — close the co-creation loop (request_change/resolve fix), 2026-06-30  (migration 009, branch `track-a/m9`)
Investigation first confirmed **no engine/API/resolve bug** (DB==API==UI; proven by `gates/api_selftest.py`). The real issues were the **open co-creation loop** + an **integrity gap** + a **UX gap**. All three fixed, additive + config-driven + audited.
1. **Distinct `CHANGES_REQUESTED` state (migration 009):** on resolve, a request_change slot moves to `changes_to` (config; `CHANGES_REQUESTED`) — NOT left at the review status. Such slots are excluded from any new gate (status-based) and **not approvable**. Rework returns them to the review status as v2.
2. **Rework trigger (no manual-CLI dependency):** `run_rework` refactored to a callable `rework_round`; API `POST /rounds/{id}/rework?stage=&dry_run=` runs it in a background thread; `GET /rounds/{id}/changes` lists awaiting-rework slots + the reviewer comment. The gateapi container now installs agents deps + `--add-host` (Ollama) so it can run the writer.
3. **Integrity guard (engine):** `decide` refuses to approve any slot at an awaiting-rework status (belt-and-suspenders with #1; permanently kills the old "approved despite a change request" silent override).
4. **Comment-responsive rework (addendum):** the reviewer comment is the PRIMARY rework directive (confirmed passed into the prompt); surgical-vs-rethink guidance ("minor → change only what was asked & preserve the rest; substantive → rethink"); v2 carries a bilingual `change_summary_ar/_en` ("how this addresses your comment"), persisted + shown in the v1→v2 revision history.
5. **UI surface:** an "awaiting regeneration (N)" panel (comment + a "Regenerate (apply my comments)" button → the trigger); the revision-history toggle shows your comment + how v2 addressed it; post-resolve disposition summary via glossary outcome labels; re-opened gates never re-pull awaiting-rework slots.
- **Tests:** `gates/api_selftest.py` extended (drives the LIVE API): request_change → CHANGES_REQUESTED → excluded from new gate → NOT approvable (guard 400) → `/changes` + `/rework` detection → in-process stub rework (`TANAGHOM_WRITER_STUB=1`) → **v2 is comment-responsive (contains the comment's directed change) + bilingual change-summary** → back to TOPIC_PROPOSED → approvable. `gates/selftest.py` updated for the new state. Both suites PASS. A deterministic `_StubRunner`/`_StubEmbed` (env-gated) makes the rework loop testable offline.
- **R3 reconciled** to the new model: the 2 pre-fix stuck slots → CHANGES_REQUESTED (awaiting-regeneration panel, comments intact); 3 approved topics → TOPIC_APPROVED. Services up (db/gateapi/bot/dashboard).

### Live dry run (R3) — staged 2026-06-30  (branch `track-a/m9`)
- **Round R3 planned** (56 slots, mix verified) + **5 real topics generated via Groq** (Scout primary; embeddings local Ollama `mxbai-embed-large`), one per pillar, clean bilingual justifications, `strategy→topic` provenance directives recorded. Topic gate **pre-opened** (5 targets). Groq daily quota had reset; no 3090 node needed.
- **Dashboard extended for the full B2/B3 lifecycle** (`dashboard/app/page.tsx`): added the manual-stage tabs (production / media_edit / distribution), **DAM media upload + list** per manual card (`POST/GET /gw/slots/{id}/assets`), the **incoming directive** ("what to deliver" + acceptance_criteria) on manual cards, and escalate/waive disposition now reachable at the manual stages (finished-media re-escalation). New glossary labels (stages + READY_FOR_PRODUCTION/PRODUCED/EDITED). `pnpm build` clean; served on :3007.
- **Services up:** db(5433) · gateapi(8009) · bot · dashboard(3007). Operational note: the **writer steps are batch jobs** I run on cue — after a topic request-change → `run_writers rework --stage topic --round R3` (regenerates v2); after topics approved → `run_writers scripts --round R3`; after a script request-change → `rework --stage script`. The reviewer drives the gates on the UI; I run the generators.
- Walkthrough order: topic digest → justification → request-change→v2 → approve → (scripts) → script review → final (escalate/waive) → production (upload raw cut) → edit (upload edit + finished-media re-escalate native) → distribution → SCHEDULED.

### M9 · Block B3 — Unified Actor Model autonomy + finished-media re-escalation, 2026-06-29  (branch `track-a/m9`)
Makes the review-discretion decision actually READ `autonomy × stage-policy × permissions` (the dims seeded on `principal` in migration 006), and lets native/scholar reviews be re-escalated on finished media — not only at the content gate. **Additive**: humans behave exactly as before; the new logic only governs non-human actors + re-escalation. No new migration (reads existing columns).
- **Policy resolver (`gates/actors.py`, pure):** `authorize_disposition(cfg, principal, review, action)` computes whether an actor may escalate/waive a review, and `authorize_gate_decision(cfg, principal, stage)` guards gate approvals. Rules: **escalation always permitted** (asking for more oversight is the safe direction); **waive** by a non-human needs autonomy ≥ `autonomous_min_level` **and** (when `require_permission`) the `review.waive` token; **hard floors** (`actor_model.hard_floors`: religious review, publish/scholar/content-sign-off gates) ALWAYS keep a human gate regardless of autonomy; default-LOW autonomy; **agents never self-escalate** (autonomy is read, never written — a low actor simply can't act as a higher one). Every autonomous decision writes an `autonomy_decision` audit row (`overridable: true`).
- **Engine wiring:** `dispose_review` consults the resolver + logs the verdict; `decide` enforces the gate hard-floor (a non-human can't decide publish/scholar/sign-off even if configured as an approver). Config `actor_model.*` (no-hardcode; bilingual copy via the glossary tokens).
- **Finished-media re-escalation (asks #2):** sign-off gates' `reviews_status` is now a LIST (`[APPROVED_ASSIGNED, PRODUCED, EDITED]`) so native/scholar can re-open over edited media; `edit_review` + `distribution_review` gained `enforce_mandatory_reviews`. Re-block is **timestamp-aware**: an escalation NEWER than the last sign-off re-opens the requirement (`_review_pending` replaces `_has_signoff`, used by both the blocker check and sign-off-gate targeting). A waived review can be re-escalated; a fresh sign-off clears it.
- **Proof:** `gates/selftest.py` now **83 checks**, ALL PASS — full lifecycle + B3: re-escalating a waived native review at the EDITED stage HOLDS the publish gate, the native gate re-targets ONLY that slot, a fresh sign-off publishes it; autonomous rep CAN auto-waive native but NOT religious (hard floor), propose_only agent CANNOT auto-waive (no self-escalation), escalation always allowed, the permission axis enforces with `require_permission`, and a non-human can't decide the publish gate. Isolation intact (R1/R2 clean, test principals cleaned, 9 real principals). `api.py` imports clean.

### M9 · Block B2 — manual lifecycle stages + minimal DAM + integration seams, 2026-06-29  (migration 008, branch `track-a/m9`)
Completes the v1 content lifecycle past content-approval, all on the existing gate engine. **Additive**: the content path through `APPROVED_ASSIGNED` is unchanged; `final_review` now CLEARS an item INTO production (`READY_FOR_PRODUCTION`) instead of straight to SCHEDULED — native/scholar are enforced **before money is spent shooting**.
- **Lifecycle (new states `READY_FOR_PRODUCTION`/`PRODUCED`/`EDITED`):** `…script_review→ APPROVED_ASSIGNED → final_review(enforce native/scholar; khal+huda) → READY_FOR_PRODUCTION → production_review → PRODUCED → edit_review → EDITED → distribution_review(publish hard-floor) → SCHEDULED → PUBLISHED`.
- **Manual stages = plain `transition` gates** (config `gates.production_review/edit_review/distribution_review`, generator=manual). **No new engine control flow** — each gate's `approve_to` chains into the next stage's `reviews_status`; the human "generator" uploads DAM assets at the stage's input state, then the gate confirms the work. B1's directive-emit-on-transition fires the next handoff automatically.
- **Directives extended:** `directives.py` adds `production_to_media` (media_directive, emitted at production_review approval, references the raw-cut DAM assets) and `media_to_distribution` (distribution_directive, at edit_review approval). `distribution` is terminal (emits null). `emit_output` dispatch covers production/media_edit.
- **Minimal DAM (`gates/dam.py` + `asset` table, migration 008):** references media via uri (no binaries in DB), versioned per (slot,stage,kind,platform_variant) with supersede-on-reupload (history kept), platform variants, audited (`asset_added`). API `GET/POST /slots/{id}/assets`; `get_gate` attaches each target's assets for the review-card preview (the review card generalizes to any artifact — only the preview differs).
- **Integration seams DEFINED + STUBBED, not integrated** (`integrations/` + `docs/INTEGRATION_CONTRACTS.md`, config `integrations.*` all `enabled:false`): one `StageExecutor` contract expressed in the B1 directive schema (`execute(directive, assets) -> {artifacts, next_directive}`); stubs for **AVP** (→ media_edit generator), **POSTIZ** (→ distribution executor behind the publish gate), **analytics** (→ strategy proposals through a review gate). `load_registry(cfg)` is empty by default (nothing wired). API `GET /integrations`; `GET /stages` (B1) lists the contract.
- **Test isolation HARDENED:** selftest seeds its throwaway round under a dedicated `selftest` tenant; a `guard_slot()` aborts any write whose slot id isn't the `RSELF-` prefix (wired into every topic/script/rework loop); `select_rework` round-scoping from B1 stays. Verified post-run: R1/R2 carry **0** directives + **0** assets; RSELF fully torn down.
- **Proof:** `gates/selftest.py` now **86 checks**, ALL PASS — the full lifecycle topic→…→SCHEDULED, DAM versioning/supersede, every handoff directive emitted (chain spans topic/script/production/media_edit/distribution), assets attached to the production gate, integration registry empty + stubs raise, an audit row for every transition incl. `asset_added`. `api.py` imports clean with the new routes.

### Backlog (M9, non-blocking)
- **token→check registry** (deferred from B2): the directive `constraints`/`acceptance_criteria` are stable TOKENS today (e.g. `no_hard_fails`, `hook_within_word_range`, `edit_uploaded`). Build a config-driven registry mapping each token → a verification function, so a gate can *programmatically* check "does the output satisfy the incoming directive's acceptance_criteria?" (the architecture's gate definition) instead of relying on writer self-checks. Pairs with the i18n glossary (same tokens render bilingual). Do when gates need automated acceptance enforcement.
- `_gate_for_rework` ambiguity: both `script_review` and `final_review` declare `rework_mode: script`; the AI rework runner only wires `script_review`. A request_change at `final_review` loops the slot back (audited) but isn't auto-rescripted. Wire/clarify when final-review rework-by-agent is needed.

### M9 · Block B1 — directive + stage contract (the backbone), 2026-06-29  (migration 007, branch `track-a/m9`)
Formalizes ARCHITECTURE.md "Inter-stage handoff = directive propagation": the pipeline is a GRAPH of stage handoffs carrying a structured **directive package**, not a flat artifact line. **Additive** — the existing topic→script flow is unchanged; directives are emitted/recorded alongside it.
- **Directive package (versioned `1.0`, six fields)** in `gates/directives.py` (PURE module, no engine dependency, imported by both the spine and the writers): `intent` (bilingual AR/EN), `inputs` (typed refs to upstream artifacts — no inlined copy), `parameters` (knobs: format/hook/lens/dialect/platform), `constraints` + `acceptance_criteria` (stable TOKENS rendered bilingual via the i18n glossary — no-hardcode-copy), `context` (provenance: pillar/HCS/lens/revision). `validate()` enforces the six fields + bilingual intent.
- **Stage contract (config-driven, `stages.<stage>`):** stage = `{ generator: ai|manual|external, consumes, emits, gate }`. `topic`+`script` are **ai** (wired); `production`/`media_edit`/`distribution` are declared **manual** seams (contract visible, gate not yet wired) so AVP/POSTIZ plug into the generator slot later without touching the engine. `directives.enabled` master switch.
- **Explicit consume/emit (the implicit made explicit):**
  - `strategy→topic` directive recorded by the topic writer = the methodology selection it fulfilled (origin provenance).
  - **`topic→script` emitted by the SPINE at `topic_review` approval** = "approved topic = directive into the script stage". One guarded call inside `resolve`'s real-transition (`cur.rowcount`) branch → idempotent.
  - The script writer **consumes** that directive (reads its `acceptance_criteria`); **`script→production` emitted by the spine at `script_review` approval** = "the script stage emits production directions".
- **Persistence + memory:** new `directive` table (slot_id, type, from/to_stage, payload jsonb, revision, produced_by, tenant/module). Every emission also writes an `audit_log` `directive_emitted` event — edges carry directives; the handoff IS memory. `get_gate` now attaches each target's incoming directive so the review surface can show "what this stage had to satisfy" (review + directives share one language). API: `GET /stages`, `GET /slots/{id}/directives`.
- **Latent bug fixed (found via the proof):** `select_rework` ran **globally** — `rework --round` was silently ignored, and the selftest reworked a real R2 slot. Now round-scoped (additive `round_id` param); `run_rework` passes `--round`; selftest scoped to its throwaway round. (The one R2 slot the test had touched was surgically restored.)
- **Proof:** `gates/selftest.py` now **61 checks**, ALL PASS on the isolated `RSELF` round (FakeChat, R1/R2 untouched): stage contract maps gates→stages, all three handoffs emitted, package well-formed (six fields + bilingual intent + acceptance_criteria), the topic→script directive carries the approved hook, revision tracked through the handoff (reworked slot → directive rev 2), and an `audit_log` `directive_emitted` row exists. Plus `api.py` imports clean with both new routes.

### UI rebuild (TASKs 2–4), 2026-06-29 — dashboard on shadcn/ui + Tailwind v4 + CopilotKit
- **TASK 2 (correctness):** explicit **round selector** (`GET /gw/rounds`); every tab scoped to **selected round + its own stage** (`GET /gates?status=open&round=`); the "open gate" bug is fixed (each tab opens ONLY its stage's gate, with `round_id`). Engine `list_gates` now returns each gate's `round_id` + a `round` filter; new `list_rounds`. **Action feedback**: toasts confirm approvals; request-change uses an inline composer (no `window.prompt`) and tells you the comment was saved + will regenerate on `rework`.
- **TASK 3 (language):** UI chrome is **English-only** via the i18n locale flip (`LANG="en"`, `lang/dir` = en/ltr). CONTENT stays bilingual — hooks/justifications render `dir="auto"`/rtl (AR) with the EN justification alongside.
- **TASK 4 (redesign):** rebuilt on **shadcn/ui (new-york) + Tailwind v4 (@tailwindcss/postcss)** — vendored Button/Card/Badge/Select/Tabs/Textarea/Separator. **"Review like a teammate" card**: WHAT (hook + angle) / WHY (justification) / RISK (suggested reviews + ⏳ blockers + writer flags), with **primary override actions** (Approve / Request-change / Reject + Escalate / Waive) and a v1→v2 revision indicator. **CopilotKit side-panel** (seeds M6): self-hosted runtime at `/api/copilotkit` backed by Groq (OpenAI-compatible); `useCopilotReadable` exposes the on-screen queue and `useCopilotAction("decideOnSlot")` lets the copilot approve/reject/request-change through the SAME gate engine. Gate engine remains the single source. Library versions verified via context7.
- **Routing:** the gate API is proxied at **`/gw/*`** (next.config rewrite) so it doesn't collide with the Next-handled `/api/copilotkit`. Dashboard env in `dashboard/.env.local` (gitignored): `API_BASE`, `GROQ_API_KEY`, `COPILOT_MODEL`.
- **Verified:** `pnpm build` compiles clean; served HTML renders (content + Tailwind CSS + CopilotKit); `/gw/rounds` returns R1/R2; `/api/copilotkit` is Next-handled. Other tabs (scripts/native/scholar/final) are functional, sharing the same components; topic-review is the polished focus per Khal's scope.
- **Other tabs are functional-but-unpolished** (inherit the shared card/components; wiring complete, visual polish later).
- Deferred to the later writer pass (Khal's call): dialect guard on justifications; surgical rework for minor edits.

### Dry run (R2, 5 Scout topics) — findings + cleanup, 2026-06-29
- **Co-creation loop PROVEN LIVE.** Khal's two change comments were captured, then `rework --stage topic` regenerated **v2** from each (v1 kept as history): `R2-D02-AM` (للوالدين→للاهل) and `R2-D03-AM` (دعاء→صلوات). See `samples/round2_topics_state.md`.
- **UI was the blocker** (engine untouched): the dashboard opened TWO `topic_review` gates and let conflicting decisions through — `R2-D03-AM` got approved *despite* a change request (silently overridden); no round scoping; no action feedback. Detail in "PRIORITY — UI is now a blocker".
- **R2 reset clean:** both comments reworked to v2; corrupted gates/decisions cleared; all 5 topics back to a clean `TOPIC_PROPOSED` for re-review on the rebuilt UI. R1 untouched. Justifications are NOT dialect-guarded yet (Egyptian leaked into a couple rationales — fold into the writer guard later).

### M5 — reviews: system SUGGESTS, reviewer DISPOSES (escalate / waive), 2026-06-29  (migrations 004–005)
- **The system flags a likely review** (writer sets `needs_native_review` on every ar-PS script; `needs_scholar_review` when an anchor is used) as a **suggestion**. The reviewer disposes per item/batch: **escalate** to the named reviewer's on-demand sign-off gate, or **waive with an audited reason**. Config-driven + role-tied; NOT hardwired.
- **Per-review policy** (`reviews.native` / `reviews.religious`, field `mode`, default **`reviewer_discretion`**):
  - `reviewer_discretion` — an un-escalated suggestion **never blocks**; reviewer MAY escalate or waive.
  - `suggested` — must be resolved (escalate→sign-off, or waive-with-reason) before publish.
  - `required` — always blocks until the named reviewer signs off; **cannot be waived**.
  - Reuses the engine's `policy: adhoc` (sign-off gates `native_review`/`scholar_review`, `kind: signoff`, open on demand, target ONLY escalated slots in discretion mode) + multi-approver. `final_review` (`enforce_mandatory_reviews`) holds a slot `blocked_on_review` only for reviews that block under the policy, then → SCHEDULED.
- **State + audit:** new `slot_review(slot_id, review, disposition, reason, actor)` table (migration 005); audit `review_escalated`/`review_waived`/`signoff_recorded`/`blocked_on_review`, attributed to the principal. Principals `nour`/`sheikh` seeded (migration 004).
- **Surfaces:** engine `dispose_review`; API `POST /slots/{id}/review/{review}/dispose`; CLI `dispose`; dashboard per-slot **Escalate / Waive** buttons + "⏳ awaiting review" chip; bilingual glossary/copy.
- **Proof:** `gates/selftest.py` now **49 checks** — discretion un-escalated doesn't block; escalating routes a slot to the scholar's on-demand gate (targets ONLY it) and blocks publish until signed; a waiver needs a reason and clears the block; flipping `mode: required` makes the same flag block regardless and rejects a waive. (Fake LLM, R1 untouched.)
- **Still to do (the HOLD):** the live full dry run on a clean Scout-only round — together.

### M4.1 BLOCK 3 — cheap foundations (avoid future retrofit), 2026-06-29  (migration 003)
- **Bilingual content fields:** `topic.rationale_ar/_en` + `topic.hook_en`, `script.script_en` (optional EN, fillable later — no migration). topic/text already `_ar/_en`. (Title/caption are distribution-phase entities; their tables will carry `_ar/_en` when created.)
- **i18n catalog + dev→user glossary** (`i18n/glossary.json` + `i18n/ui.json`, AR/EN, externalized): statuses/decisions/stages/flags/terms/roles render as **business lexicon** (e.g. DRAFT_ASSIGNED → "بانتظار المراجعة / Awaiting review", request_change → "يحتاج تعديل"). ONE canonical source: the bot reads it via `gates/i18n.py`; the dashboard fetches it from **`GET /api/i18n`** (no inline UI strings).
- **Principal model** (`principal` table + 7 seeded: khal/huda users, agent.planner/topic/script + writers agents, system): humans, system agents, and future per-user agent reps are all first-class identities with roles. Gate `approvers` reference principal IDs (khal/huda), not free-text.
- **Attribution on every event** (`audit_log.actor_kind`): `_audit` classifies the actor via the principal registry (user|agent|system). Surfaces now pass the acting **principal** as the actor (dashboard + Telegram send khal/huda, not the channel); the writer agents log as `agent`. Verified: `gate_decision by khal [user]`, writers as `[agent]`.
- **Tenant + module scoping** (`tenant_id` default `default`, `module` default `content`) on round/slot/topic/script/gate/audit_log — multi-tenant/department scoping is a default now, not a future migration. No multi-tenant UI (per "don't over-build").
- **Proof:** `gates/selftest.py` still 31/31 PASS after the schema + attribution changes; dashboard builds clean; `/api/i18n` serves the glossary.

### M4.1 BLOCK 2 — config hygiene (no-hardcode), 2026-06-29
- `surfaces.telegram_approver_chat_id` set (1586709845). Bot authorization is now **explicit**: only the configured approver chat may act (removed the `or ["khal"]` fallback and the implicit-allow when the chat id is unset).
- Dialect-guard hard markers include عايز / عاوز / عايزين (+ the BLOCK 1 additions).

### M4.1 notes (BLOCK 1 — corrected content-review flow, 2026-06-29)
- **Two-stage flow, config-driven** (`gates.<stage>.reviews_status`/`approve_to`): Planner→RESERVED → `run_writers topics` → **TOPIC_PROPOSED** → `topic_review` → **TOPIC_APPROVED** → `run_writers scripts` (approved topics ONLY) → **DRAFT_ASSIGNED** → `script_review` → **APPROVED_ASSIGNED** → `final_review` (khal+huda) → SCHEDULED. New enum states via `db/migrations/002_m4_two_stage.sql`.
- **Runner split** (`agents/run_writers.py`): modes `topics` / `scripts` / `rework` / `bakeoff` (was the single `write`). `process_slot` → `process_topic` + `process_script`.
- **Topic justification:** the topic agent now emits a concise **bilingual** reviewer rationale (`rationale_ar`/`rationale_en` — "why this topic now") persisted on the `topic` row and surfaced at the topic gate (dashboard + Telegram), NOT the script.
- **Co-creation loop:** request-change requires a comment (engine enforces) captured in BOTH surfaces (dashboard prompt; Telegram "reply with what to change" — the hardcoded "via telegram" is gone). `run_writers rework --stage topic|script` re-runs the agent with the note injected as a NEW revision; prior version kept (`topic.revision/feedback`, `script.revision/feedback`) = history.
- **Telegram is summary-first:** `/review [topic|script]` sends ONE digest (counts + by-pillar + flags) with batch buttons (Approve all / Open dashboard / Step through); no per-slot spam. Verbosity in `surfaces.telegram_ux` (config).
- **Proof:** `gates/selftest.py` runs the whole pipeline on an isolated `RSELF` round with a fake LLM (no Groq), leaving R1 untouched — 31 checks incl. scripts-only-on-approved, topic regenerates from the comment, revision history, multi-approver quorum, and an audit row for every transition.

### M4 run guide (updated for two-stage)
1. **Stack:** `docker compose up -d db adminer`  · **API (8009):** `uvicorn gates.api:app` (in the container, `-p 8009:8000`) · **Dashboard:** `cd dashboard && API_BASE=http://localhost:8009 pnpm dev` · **Bot:** `python gates/bot.py`
2. **Writers (two-stage):** `python agents/run_writers.py topics --round R<n>` → review topics → `... scripts --round R<n>` → review scripts. Rework: `... rework --stage topic|script`.
3. **CLI gate ops:** `python gates/cli.py open|list|show|decide|resolve`.

### M4 notes (gates + surfaces, 2026-06-29)
- **One source of truth:** all transition logic is in **`gates/engine.py`**; the CLI, the FastAPI (`gates/api.py`), and the Telegram bot (`gates/bot.py`) all call it. The Next.js dashboard calls the API. **n8n is deliberately OUT of the approval path** (reserved for the later distribution phase).
- **Engine proven** by `gates/selftest.py` (21 checks, idempotent — resets R1 clean): partial-batch (approve 50/56, send 6 back), reject + request_change loop-back (stay DRAFT_ASSIGNED), **multi-approver quorum** (`final_review` = khal+huda, `all` → both must approve; 1/2 pending, 2/2 approved), reject precedence, an `audit_log` row for **every** transition, approved → `APPROVED_ASSIGNED`, and guards (resolved-gate / unknown-approver rejected).
- **Config-driven** (`system_config.yaml` `gates.<stage>`): `script_review` (khal, quorum any), `final_review` (khal+huda, quorum all). quorum any|all|N resolved to an integer at open-time.
- **Dashboard** (`dashboard/`, Next.js 15 App Router, RTL/Arabic): review queue with per-row + bulk approve/reject/request-change, script preview, scholar/native + writer flags, approver selector, resolve. Builds clean; `/api/*` proxied to the API (`next.config.mjs`, `API_BASE`).
- **Telegram** (`gates/bot.py`, python-telegram-bot): `/start` replies the chat id (capture into `surfaces.telegram_approver_chat_id`), `/pending` pushes each slot with inline ✅/✏️/❌, `/approve_all`, `/resolve`. Bot = **@Khal_stitch_1_bot**. With `telegram_approver_chat_id` empty any chat acts as the first approver — set it after `/start` to lock down.
- **Ports (all configurable; macOS conflicts resolved):** DB host `5433` (`DB_PORT`), n8n `5681` (`N8N_PORT_HOST`), API host `8009` (`-p 8009:8000`; 8000 was taken), dashboard `3000`, Adminer `8080`.

### M4 run guide (three terminals)
1. **Stack:** `docker compose up -d db adminer`
2. **Gate API (8009):** `docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 -p 8009:8000 -v "$PWD":/work -w /work python:3.12-slim bash -lc "pip install -q -r gates/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000"`
3. **Dashboard (3000):** `cd dashboard && API_BASE=http://localhost:8009 pnpm dev` → http://localhost:3000
4. **Telegram bot:** `docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 -v "$PWD":/work -w /work python:3.12-slim bash -lc "pip install -q -r gates/requirements.txt && python gates/bot.py"` → message **/start** to @Khal_stitch_1_bot
   - (CLI alternative for any step: `python gates/cli.py open|list|show|decide|resolve`.)

### M3 round-complete notes (macOS rebuild, 2026-06-28)
- **Platform moved off the Windows/3090 box to macOS** (no GPU). Docker + Ollama run locally; writers/loader/planner still run in throwaway `python:3.12-slim` containers on the `tanaghom_default` network.
- **Writing backend switched to Groq** (config-only). `system_config.yaml`: `topic_hook`/`script` primary = `groq:meta-llama/llama-4-scout-17b-16e-instruct`, fallback = `groq:qwen/qwen3-32b`. Embeddings stay local: `ollama_embed:mxbai-embed-large` (1024-dim). Gemini `reasoning_effort` param removed. `GROQ_API_KEY` in `.env`.
- **Groq free-tier limits matter:** Scout = 30k TPM, Qwen3-32B = only 6k TPM (per-minute, resets each minute). The persistent-429/quota fall-through was re-applied in `providers.py` and now correctly treats **TPM as transient (retry)** vs **daily/RPD/quota as persistent (fall through)** — the `billing` upgrade-URL false-match was the bug. `groq` provider gets `max_retries: 6`, `retry_base_seconds: 12` to ride the resets.
- **Round outcome:** 56/56 DRAFT_ASSIGNED. Models served: **54 Scout, 2 Qwen** (fallback fired on Scout TPM spikes: R1-D06-AM, R1-D13-AM). **12 dedup regenerations**, **2 dialect-guard hook regenerations**, **0 persisted hook-check failures**. Flags: `needs_native_review` on all 56; `needs_scholar_review` on 28 (islamic_anchor used); `script_hard_fail` flagged on 2 (R1-D11-PM, R1-D14-AM) — review these first.
- **Bugs fixed this pass (were latent, never hit by the 3-slot preview):**
  1. `nearest_similarity` indexed a RealDictCursor by position (`row[1]`) → `KeyError` on the first dedup hit (repeat HCS within a round). Now uses `row["sim"]`/`row["text_ar"]`.
  2. `parse_json` now extracts the **first balanced** JSON object (handles models emitting `{...}{...}` / trailing prose) and uses `strict=False` (tolerates literal newlines inside `script_ar`).
- **Host port note:** macOS host `5432` was taken by another project's Postgres, so compose now publishes `${DB_PORT:-5432}:5432` and `.env` sets `DB_PORT=5433`. In-container runs override `-e DB_PORT=5432` (the network-internal port). Adminer at http://localhost:8080 (server `db`).

### M3 quality pass (dialect guard + anchor verifier, 2026-06-28)
- **Dialect guard expanded** (`writers.dialect_guard`): added hard Egyptian markers (بتاعة، بتاعتك، ده، دي، دول — the short demonstratives are safe because matching is Unicode word-boundary `\b…\b`, so Palestinian بده/هدول/عنده do NOT trip) and a new **`soft_markers`** tier (حاجة، حاجات) that warns + flags `dialect_soft_warn` but never forces a regenerate.
- **Islamic-anchor rule tightened** (`writers.islamic_anchor`): omit-by-default prompt; `require_justification` (a used anchor with no organic justification regenerates without it); and **`verify: true`** — an adversarial second-opinion pass (`verify_anchor_organic`, default REMOVE on doubt) because the writer self-certifies *every* anchor as organic. Non-organic anchors are pruned and the script is rewritten without scripture (flag `anchor_pruned`).
- **Re-run outcome (this is the current DB state):** 56/56 DRAFT_ASSIGNED. **Anchors 24/56** (was 28/56; verifier pruned 4: R1-D03-AM/P5, R1-D05-AM/P4, R1-D11-AM/P1, R1-D26-PM/P1). **R1-D02-AM (P3) misapplied verse → now removed.** Flags: `needs_native_review` 56, `needs_scholar_review` 24, `anchor_pruned` 4, `script_hard_fail` 3 (R1-D06-AM, R1-D12-PM, R1-D19-AM — real Egyptian leakage caught), `dialect_soft_warn` 3 (R1-D03-AM, R1-D06-AM, R1-D13-AM), `near_duplicate` 1.
- **Groq has a DAILY token cap too:** Llama 4 Scout = **500k tokens/day (TPD)** on the free tier. Three full round-runs + the anchor verifier exhausted it, so the back half of this re-run fell through to **Qwen3-32B (22 slots vs 34 Scout)**. The TPD 429 is correctly classified persistent. For a clean single-model round, either wait for the daily reset or upgrade the Groq tier. Qwen's 6k TPM also truncates the topic stage if its hidden reasoning eats the 1500-token budget — bump that stage's `max_tokens` for Qwen-heavy runs if needed.

### M3 notes (for the next agent)
- Writers: `agents/run_writers.py` (Agent 1 Topic + Agent 2 Script) + `agents/providers.py`. Driven by `system_config.yaml`; run instructions in `agents/README.md`.
- **Backends auto-detected on this box:** writing = frontier via **OpenRouter** (`OPENROUTER_API_KEY`, default `anthropic/claude-sonnet-4.6`); embeddings = local **Ollama `mxbai-embed-large`** (1024-dim, matches `topic.embedding`). Ollama reached from the container via `--add-host=host.docker.internal:host-gateway`.
- Agent 1: topic_angle + hook_text + hook_type, or `NEEDS_STRATEGIC_CLARIFICATION`. Spoken hook hard-checked vs CANON-013 (3–7 words, no greeting, no "معتز", one person) and regenerated on violation. Then embedding **dedup** vs the `topic` ledger within `engine.dedup_safety_net.scope` (default `hcs` → guards repeated HCS across cycles/rounds); regenerates on near-dup ≥ threshold.
- Agent 2: `script_ar` enforcing CANON-013 Hard Fails + the CANON-012 Mandatory Delivery Check; sets **needs_scholar_review** when an `islamic_anchor` is used, **needs_native_review** for dialect. Writes `topic` + `script` rows, `slot.script_ref`, moves slot **RESERVED → DRAFT_ASSIGNED**, audits each transition. One transaction per slot.
- **Schema added this milestone** (in `schema.sql` + idempotent `db/migrations/001_m3_writers.sql`): `slot.cycle_no`, `topic.round_id/cycle_no`, and the new **`script`** table. Planner now persists `slot.cycle_no`; planning state was truncated + R1 re-planned so slots carry it.
- **Preview result:** R1-D01-AM (P1 Stress) and R1-D01-PM (P2 marriage) generated end-to-end and persisted to DRAFT_ASSIGNED with strong ar-PS voice + correct flags. R1-D03-AM (P5) generated a full script in dry-run but its **persist was blocked by OpenRouter running out of credits (HTTP 402)** — not a code issue. DB now: 2 DRAFT_ASSIGNED, 54 RESERVED.
- **Before the full 56-slot round:** top up OpenRouter credits (~$ a few). `providers.py` now fails clearly on `finish_reason=length` (raise the stage `max_tokens` if a script truncates). Token budgets: topic 1000 / script 1500.

### M2 notes (for the next agent)
- Planner: `planner/plan_round.py` (`plan` | `verify`). Driven entirely by `system_config.yaml`; run instructions in `planner/README.md`.
- `plan` generates one round of 56 slots at status **RESERVED**: pillars round-robin-spread to the per-round mix (22/17/9/4/4), formats to the per-week mix (4/1/2/2/3/1/1 ×4 weeks). HCS assigned by walking `hcs.seq_in_pillar` from per-pillar `hcs_cursor` (wraps + `cycle_no++` on exhaustion; **carried across rounds**). Lens from `recommended_lenses` excluding the prior cycle's lens → `lens_history`; hook from `lens.default_hook_type`. Atomic; writes `audit_log` per transition.
- **Acceptance proven:** ran R1 then R2. Cursor continued (e.g. P1 1.9/c2 → R2 starts 1.10/c2; P4 4.4/c1 → 4.5). Lens rotation: **0 consecutive-cycle repeats**; every HCS shared by R1+R2 got different lenses in R2 (e.g. 1.1: R1 L1/L2 → R2 L3/L5). `verify` reprints this proof from the DB.
- A pillar can cross a cycle boundary **within one round** (P1: 13 HCS but 22 slots), so `lens_history` is keyed `(hcs_id, cycle_no)` — this is expected, not a bug.
- DB now holds 2 rounds × 56 RESERVED slots. To reset planning state for a clean demo: `TRUNCATE slot, round, lens_history, hcs_cursor, audit_log;` (methodology tables untouched).

### M1 notes (for the next agent)
- Stack: only `db` + `adminer` brought up. **`n8n` (5678) was NOT started — host port 5678 is already taken by another container.** Not needed until M4; resolve the port (or stop the other n8n) then.
- Config: `system_config.yaml` and `.env` created locally (gitignored); `DB_PASSWORD` is a random 48-char hex in `.env`.
- Loader: `loader/load_methodology.py` parses the canon + 42 records from markdown and UPSERTs into `pillar/lens/hook_type/format/hcs`. Idempotent + self-verifying. Run instructions in `loader/README.md`.
- Verified counts: 5 pillars · 42 HCS (13/8/8/6/7) · 5 lenses · 5 hook types · 7 formats. `pillar_code` mapped P1→`P1_SELF` etc.; `hcs.seq_in_pillar` holds the canon walk order for the cursor.

## Decisions log
- Hosting: **moved to macOS (no 3090)** as of 2026-06-28; was local Windows/3090. Docker + Ollama local; data stays local.
- Voice-critical generation: **Groq** (Llama 4 Scout primary, Qwen3-32B fallback) — replaced the Gemini/OpenRouter setup. Embeddings/ASR: local Ollama (`mxbai-embed-large`).
- Build tools: Claude Code + Codex (interchangeable).
- Open: value-ladder canon (Phase 3), Agent 2/3 reconciliation, X/LinkedIn timing.

## Notes / blockers
- _(append as they arise)_

---
## Returning to this project (Claude / agent onboarding)
If you are a fresh Claude/Cowork session or coding agent picking this up (e.g. on another machine after `git clone`):
1. Read this file top-to-bottom.
2. Read `README.md`, then `docs/01_Blueprint_v2.md` and `docs/02_Phase1_Build_Spec.md`.
3. Skim `docs/05_Voice_Performance_Calibration.md` (voice rules) and `methodology/` (canon + 42 records).
4. Resume from the first unchecked milestone above. Keep all behavior in `system_config.yaml`; keep every stage gated and audited.
This repo is the single source of truth and portable memory — context travels with it, not with any one chat.

---
## M4 prep notes (read before building gates + n8n)
- **Port conflict (Mac):** other n8n instances already run in Docker on this Mac. Before starting n8n, check used ports (`docker ps`, `lsof -i :5678`) and **remap n8n to a free host port** in `docker-compose.yml` (e.g. 5679+). Same caution as the Windows box.
- **Version-aware build (n8n + all components):** n8n's workflow/node JSON and node parameters change between versions, so always:
  - Check the installed component versions first (n8n image tag, node versions, library versions) — don't assume.
  - Build against the **latest official version-specific documentation**, not memory.
  - Use **context7** (available in Claude Code) or equivalent to pull current docs/syntax before writing workflows or node configs; verify node names/params against the running version.
- Applies generally (Postgres, pgvector, Remotion, providers) — pin/verify versions and consult current docs to avoid deprecated syntax.
- **Prefer native n8n nodes over code:** n8n's value is its rich native node library — use built-in nodes (HTTP, Postgres, IF/Switch, Merge, Telegram, etc.) and expressions wherever possible. Only drop to a Code/Function (JS) node when no native node covers the need. Do NOT invent nodes: every node used must exist in the installed n8n version (verify against context7/official node reference); no obsolete, renamed, or imaginary nodes/params.
- **n8n management via MCP:** at M4, set up an n8n **MCP server** so Claude Code can create, manage, and test workflows programmatically. Steps: (1) bring up n8n (remapped port), (2) Kay registers/generates an **n8n API key** in the n8n UI and provides it (store in `.env`, gitignored), (3) configure a current/maintained n8n MCP pointed at the local instance with that key, (4) **confirm n8n connectivity via the MCP** before building workflows. Verify the MCP is compatible with the installed n8n version (context7/docs).

---
## Backlog: Planner v2 — flexible periods + ad-hoc (requirement: calendar is NOT fixed to 28 days)
Status: partially covered. Do after M4.
- [x] Different period length — already works via config `templates` (e.g. add a `weekly` template; `plan --template weekly`). Parametric grid from period_len/posts_per_day/post_times; weekly format mix repeats.
- [ ] **Ad-hoc command (`plan-adhoc`)** — NOT yet built. Create N one-off slots with optional constraints (pillar / HCS / format / platform / date); respect `adhoc_consumes_cursor` (off-cycle by default); route through the same gates. Config flags exist (`allow_adhoc_slots`, `adhoc_consumes_cursor`) but no code path.
- [ ] **Arbitrary length / partial weeks** — format distribution currently assumes whole weeks; add handling (or a proportional allocator) for non-7-multiple periods.
- [ ] Verify cursor + lens-rotation integrity across mixed period sizes and ad-hoc insertions.
- Note: ad-hoc *approval* (fixed vs on-demand gates) is separate and handled in the M4 gate engine.

---
## CORE PRINCIPLE — nothing hardcoded (applies to ALL milestones)
Every value that could reasonably change lives in `system_config.yaml` (or env/DB), never baked into code. This includes — and is not limited to:
- calendar periods, posts/day, post times, pillar & format distributions, templates
- models/providers per stage, params (temperature, max_tokens, reasoning_effort), fallback chains
- dialect-guard markers (hard/soft), anchor rules/thresholds, dedup similarity threshold, exemplar counts
- prompts/system instructions (externalized, editable), gate policies (scope/quorum/approvers), review-flag rules
- ports, paths, base_urls, schedules, platform targets, thresholds and magic numbers
Rule of thumb: if a reviewer might ever want to change it without a developer, it must be configurable and (eventually) editable from the settings UI. Run a quick "no-hardcode audit" at each milestone.

---
## UI / UX & Localization principles (polish deferred — but scaffold early)
Polish/visual judgement is deferred. These requirements are NOT deferred as design constraints; adopt the cheap ones now to avoid costly retrofit.

**Bilingual**
- Interface is **bilingual Arabic + English**, **Arabic-primary & RTL**. Topics, titles, captions stored & shown **bilingual (AR + EN)**.
- Scripts: **Arabic Palestinian dialect primary**. EN localization/translation of scripts is **optional/future** (useful for non-Arabic stakeholders) — design fields to allow it, don't require it.
- Implication: content data model carries bilingual fields (topic/title/caption: `*_ar` + `*_en`); script `script_ar` now, optional `script_en` later.

**Speak the business/workflow language, not code**
- UI (and Telegram) copy uses **content-workflow & business vocabulary**, never engineering/DB lexicon. Maintain a dev→user **term glossary** (AR/EN) the UI renders from. Examples:
  - slot → "Post / منشور"; round → "Content plan (period) / خطة المحتوى"; DRAFT_ASSIGNED → "Awaiting review / بانتظار المراجعة"; APPROVED_ASSIGNED → "Approved / معتمد"; request_change → "Needs edits / يحتاج تعديل"; gate → "Review / مراجعة"; HCS → show the struggle *name* (hide codes like 1.2); lens → "Angle / زاوية"; needs_native_review → "Language review / مراجعة لغوية"; needs_scholar_review → "Religious review / مراجعة شرعية".
- Human-friendly statuses (Draft → In review → Approved → Scheduled → Published), human audit phrasing ("Huda approved on …"), platform-native labels (Instagram Reel, TikTok) not internal format codes.

**Adopt now (cheap; costly to retrofit later)**
- **i18n layer from the start**: all UI strings in externalized resource catalogs (AR/EN), never inline — this is the no-hardcode rule applied to copy. Enables language toggle + wording changes without code.
- **Domain labels via the glossary**, not raw enum/field names, even in the first rough UI.
- **Bilingual content fields** in the schema now (so EN can be filled later without migration).

**Expanded considerations (likely needed; confirm with Kay)**
- **Role-based views**: content owner (Khal/Moataz), language reviewer, scholar reviewer — each sees the relevant queue (e.g. scholar sees only slots with a religious anchor pending). Ties to multi-approver gates.
- **Localization details**: Arabic vs Latin numerals, date/time format, UAE timezone display; RTL-correct mixing of Arabic + Latin/links.
- **Plain-language empty states, errors, tooltips, confirmations** (non-technical users).
- **Brand identity** (Tanaghum/Moataz visual system: logo, colors, type) — deferred but reserve for it.
- **Telegram copy** bilingual + business lexicon too (e.g. "5 posts ready for your review" not "gate opened").

---
## M6 — User-Agent copilot (conversational "Agent rep") — V1 SCOPE, not yet built
Core to the blueprint (control plane: the User-Agent rep), explicitly required, currently MISSING from the dashboard. It is the PRIMARY way a non-technical user drives the system — an always-available AI copilot (chat panel in the dashboard; also powers natural-language Telegram), like any modern agent setup.

**What it must do (natural language, bilingual AR/EN, business lexicon):**
- Plan: "اعملي خطة أسبوع" / "plan next 28 days" → calls the Planner.
- Status: "شو مستني مراجعتي؟" / "what's awaiting me?" → queries gates/slots.
- Act: approve/reject/request-change by instruction ("approve all parenting posts", "ارفض البوست الفلاني").
- Iterate: "redo 3.4 with a different angle/lens", "اكتبيلي هوك تاني لهاد".
- Explain: answer questions about the methodology, coverage, why a slot got a given HCS/lens.

**Architecture (reuse, don't duplicate):**
- The copilot is an **agent with tools** = the existing engine functions exposed as callable tools (plan_round, plan_adhoc, open_gate, decide/resolve, regenerate_slot, query_state, etc.). One engine, now also driven by NL — same source of truth as dashboard/Telegram/CLI.
- Keep a clean **tool/API boundary** so the copilot is swappable: later it can be the user's OWN agent (Claude/Codex) via API/MCP (per blueprint).
- Model for the copilot itself is config-driven (no-hardcode); can differ from the writing model.

**Sequencing:** build after M5, before heavy UI polish — it's how the product is meant to be used, so it belongs in the v1 "content brain" release, layered over the proven engine + gates.

---
## M7 — "Living operation": multi-agent presence & activity view (UX vision)
The user interacts with ONE agent (their own AI twin / rep), but the UI surfaces ALL agents in action — system specialist agents and other users' agent reps — so the company's autonomous operation comes alive: agents generating, handing off, reviewing, approving, collaborating with the user and each other in real time.

**Single interaction, full visibility:** user drives via their own twin only; other agents are observable (not directly puppeted) and collaborate through the system (requests/handoffs/approvals).

**What it needs (much of the data foundation already exists):**
- **Agent registry/roster** — every agent (system + per-user reps) is a first-class entity: identity, role, owner, status (idle / working / waiting-on-human), current task. Config-driven (no-hardcode).
- **Agent attribution on every transaction** — extend the existing `actor`/`audit_log` so each event records WHICH agent/user did it. (CHEAP TO ADD NOW; costly to backfill — adopt early.)
- **Live activity/event feed** — render audit_log as a real-time, human-readable, bilingual stream ("Planner built 56 drafts", "Huda's rep approved 50, flagged 6", "Distributor scheduled 14"). Business lexicon, not code.
- **Live workflow/org view** — the architecture diagram made live: which stage each item is at, which agent holds it, where humans are needed.
- **Real-time/presence** — websockets/polling so agents visibly "come alive" as work flows.
- **Multi-user, multi-rep** — multiple humans, each with an agent rep that can act on their behalf (reviews/approvals); ties to role-based views + multi-approver gates.
- **Permission boundaries** — visibility ≠ control; clear authz on who/which agent can act.

**Sequencing:** richer UX layer, after the content brain works (M4–M6) and as real operation begins (Phases 2–3 make it lively). Build the live view later, but **capture agent attribution in the event stream now** so it isn't a retrofit. Config-driven, bilingual, one-event-source (reuse audit_log) per the core principles.

---
## M8 — Identity, Access & Provisioning (IAM / Admin) — foundational; standard + agent twist
Standard enterprise capability, must not be missed. Underpins M4 (approvers), M6 (copilot delegation), M7 (agent registry/visibility).

**Standard:** users, roles & permissions (RBAC), authentication, provisioning lifecycle, admin/settings UI, full audit, least-privilege, separation of duties.

**The twist — unified principal model:** humans, **system AI agents**, and **per-user AI agent reps** are ALL first-class principals with identities and privileges.
- Per-principal privileges (least privilege): e.g. Writer agent = generate, not approve; reviewer/rep = approve within scope; the user's **twin acts on behalf of the user** (bounded delegation) — and **audit records both** the acting agent AND the human it acted for.
- Provisioning: create/invite users, assign roles, **provision each user's agent rep**, enable/disable, revoke, rotate agent keys/credentials.

**Ties / fixes:**
- Gate `approvers` currently reference free-text names ("khal","huda") → must become **real provisioned principals** (IDs).
- Event attribution (M7) references principal IDs.
- Role-based views (UI principles) derive from roles here.

**Future:** org/workspace scoping (multi-brand / multi-tenant — Taatheer has multiple ventures); SSO/IdP integration.

**Adopt early (cheap; avoids retrofit):** a **minimal principal model** now (users + agents as identities + roles) so approvers and event attribution reference real IDs, not strings. Full admin UI + auth/SSO before any multi-user/production deployment.

**Principles:** config/data-driven (no-hardcode), bilingual + business-lexicon admin UI, everything audited.

---
## GOVERNING PRINCIPLE — platform, not app (multi-tenant, multi-department, decoupled, extensible)
Treat the content department as the FIRST module on a reusable platform. Sustain agility / decoupling / extensibility as a first-class quality. Future: other departments + multi-tenant (multiple brands/clients — Taatheer's ventures).

**Shared platform services** (reused by every module): IAM/principals, agent registry + capability matrices, gates/approvals engine, audit/event stream, config, copilot + tool/MCP boundary, provider registries.
**Domain modules** (swappable, self-contained): methodology, planner, writers, edit/distribution = content-dept specific; another department brings its own, plugging into the same platform services.

**Decoupling:** clean, stable module↔platform interfaces/contracts so parts evolve independently; no cross-module hardcoding; communicate via the shared event stream + APIs, not tangled calls.

**Adopt cheap NOW (avoids painful retrofit):**
- Add `tenant_id` (and a `module`/`department` tag) to core tables now — default single tenant — so scoping isn't a future migration.
- Module-oriented code layout (content-dept code separable from platform code).
- Keep interfaces stable (gates engine, copilot tools, provider/agent registries already point this way).

**Engineering nuance (don't over-build):** the discipline is clean boundaries + scoping keys + config — NOT building a full plugin/module framework before the first module is proven. Maintain the seams; defer the abstraction machinery until a 2nd tenant/department actually arrives.

Reinforces: no-hardcode, config/data-driven, capability matrices, one-engine-many-surfaces, event-sourced audit.

---
## Request-change feedback loop (co-creation) — make functional+architectural NOW (UX later)
Standard in AI co-creation tools: reviewer comment → regenerate INFORMED by it → revised draft → back to review, with iteration history. Current state: data field exists (`gate_decision.notes`) + engine accepts notes, but the loop is NOT closed.

Gaps to fix (part of M4.1 / M5):
- [x] **Capture the comment** on request-change in BOTH surfaces. Telegram now asks "reply with what to change" (ForceReply); dashboard prompts for a required comment; engine rejects an empty request-change note.
- [x] **Close the loop:** `run_writers rework --stage topic|script` re-runs the relevant agent for the changed slot with `gate_decision.notes` injected; revised draft re-enters the gate.
- [x] **Revision history:** `topic.revision/feedback` + `script.revision/feedback` keep prior versions + the feedback that drove each; traceable, feeds audit + M7 living view.
- Defer (polish): inline/per-line comments, diff view, threaded comments.
- Principles: notes/feedback are data (no hardcoded placeholder), bilingual, audited.

---
## PRIORITY FIX — split Topic and Script into two gated stages (topics approved BEFORE scripting)
Deviation from spec: M3 runner generates topic+script in one pass (RESERVED → DRAFT_ASSIGNED with full script). Per methodology, TOPICS must be proposed/reviewed/approved FIRST; only approved topics get scripted. Design already supports it (gates `topic_review` + `script_review` exist; `generate_topic`/`generate_script` already separate). This is re-sequencing, not redesign. Do BEFORE M5.

**Corrected flow:**
- Planner → `RESERVED`
- Topic agent only → topic_angle + hook → **`TOPIC_PROPOSED`** (NEW state)
- `topic_review` gate (topics only) → **`TOPIC_APPROVED`** (NEW state)  [reject/request-change → topic regen, per co-creation loop]
- Script agent runs ONLY on `TOPIC_APPROVED` → script (+ production directions) → `DRAFT_ASSIGNED`
- `script_review` gate → `APPROVED_ASSIGNED`

**Changes:**
- [x] Add slot_status states `TOPIC_PROPOSED`, `TOPIC_APPROVED` (migration 002).
- [x] Split runner into `topics` (RESERVED→TOPIC_PROPOSED) and `scripts` (TOPIC_APPROVED→DRAFT_ASSIGNED) + `rework`.
- [x] Wire `topic_review` over TOPIC_PROPOSED; `script_review` over DRAFT_ASSIGNED (config `reviews_status`/`approve_to`).
- [x] Surfaces: topic stage shows topic + hook + why-now (no script); script preview at the script stage.
- [x] Cost win: only approved topics get scripted (`scripts` selects TOPIC_APPROVED).
- Principles: states/config-driven, bilingual, audited; integrates with the request-change co-creation loop.

### Topic justification at the topic gate (part of the two-stage fix)
- [x] Persist the topic rationale (`topic.rationale_ar` / `topic.rationale_en`).
- [x] Reviewer-facing & concise "why this topic now", **bilingual** (AR/EN), business lexicon — not the script.
- [x] Surfaced at the `topic_review` gate (dashboard "why now" block + Telegram digest/step-through).

### Telegram UX — summary-first (practical now)
Telegram must NOT push one message per item (overwhelming/unmanageable). Surface division:
- **Telegram = digest + batch actions + notifications** (on-the-go, lightweight). One summary per stage/batch: counts + breakdown (by pillar) + flags, with batch buttons (Approve all / Open dashboard link / step through a few on demand). Summarized notifications ("6 topics need edits", "14 ready to publish").
- **Dashboard = detailed per-item review.**
- Verbosity/summary-vs-itemized is config-driven (no-hardcode). Keep simple now; Telegram mini-apps / inline web apps later.

### Working rule — leverage available skills / plugins / MCPs (don't reinvent)
Before building a specialized task, the build agent (CC) should survey available skills/plugins/MCPs/tools and use the best-fitting one rather than coding from scratch. Verify it's current/compatible (context7/version-check) and keep it behind a clean interface (capability-matrix / no-hardcode). Indicative task→capability map (use when applicable):
- n8n workflows → **n8n MCP**; current library docs/syntax → **context7**.
- carousels/images → **design skills / Pencil / Figma**, ImageMagick / imagesorcery for templated bulk.
- video edits → **Remotion** (+ any video skill/MCP).
- production docs / reports / guidelines → **docx / pdf** skills.
- web data (competitors, trends, research) → search / web-data tools/MCPs.
- design critique / UX / accessibility → **design skills**.
This is the same principle as the future Tool/MCP capability matrix — applied now by CC choosing the right tool per task/specialization.

### Foundations — follow-ups (non-blocking, from Block 3 review)
- Bilingual fields now cover topic/hook/rationale/script. **title/caption `*_ar`/`*_en` to be added when those artifacts exist** (platform-formatting phase).
- **Habit: tenant-scope queries** (filter by tenant_id) from now on, even with the single default tenant, so it's never a retrofit.
- **Per-user agent-rep principals** (the user's AI twin) come with M6/M8; principal model already supports them.
- **Delegated-actor attribution** (agent acting on-behalf-of a human → record both) to be added at M8 when delegation exists.

### Review gates: reviewer-controlled + external guest approvers (refines M5)
Do NOT hardwire scholar/second review. Two parts:
**A. Reviewer-controlled optional gates (part of M5):**
- System FLAGS likely candidates (e.g. anchor used) as a suggestion, not an automatic hard requirement.
- Reviewer decides per item/batch: **escalate** to a scholar (or any named second approver) OR **skip/waive** with a reason (audited).
- Config policy sets default + lets org tighten later: e.g. `reviews.religious.mode: reviewer_discretion | suggested | required` (default reviewer_discretion). Reuses gate engine `policy: adhoc` + multi-approver. No-hardcode / human-in-control.
**B. External/guest approver via secure link (M5.x feature, before real external reviewers):**
- Scoped, expiring, tokenized link → lightweight web review page (item + context, approve/reject/comment) for approvers who are NOT system users (sheikh, client, guest editor).
- Delivered via Telegram now (WhatsApp/email later) — channel just carries the link.
- Decision writes back through the SAME gate engine (single source); attributed to a **guest/external principal** (principal model + M8 authz). One-time/expiring, scoped, minimal access, audited.
- Generalizes to any ad-hoc external reviewer, not just the sheikh.

---
## CONCEPT (refined) — Unified Actor Model + policy-driven autonomy (frames M8 + capability matrices + gates)
Every actor (human user, AI agent, agent rep/twin, guest/external) shares ONE identity spine (principal model) + three SEPARATE axes + scope:
- **Capabilities** — tools/skills/models it CAN use (capability matrix).
- **Permissions** — what it's ALLOWED to do (RBAC/ABAC).
- **Autonomy** — how independently it acts: `propose_only | recommend | act_with_approval | act_and_notify | autonomous`.
- **Scope** — tenant / module / workflow / stage.
Behavior is COMPUTED: at each step, propose vs request-review vs act = f(autonomy × stage-policy × permissions). (The reviewer-controlled scholar gate is the first instance.)

**Safety guardrails (non-negotiable):**
- Default LOW autonomy; raising it is an explicit, scoped, reversible ADMIN action; agents NEVER self-escalate.
- **Hard floors regardless of autonomy:** publishing, spending, religious content always keep/offer a human/scholar gate. Autonomy operates inside guardrails.
- Most-restrictive-wins on policy conflict. Every autonomous decision logged with reason + human-overridable.
- Don't over-fuse: shared framework, but type-specific (humans=login/UI; agents=keys/tools; autonomy applies to AI actors).

**Adopt now vs later:**
- NOW (cheap): add dimensions as DATA on the principal model — `type`, `roles`, `permissions`, `capabilities`, `autonomy_level`, `scope` — defaulting safest; implement ONLY the review-discretion decision reading autonomy+policy.
- LATER (M8+): admin UI, full policy-resolution engine, dynamic capability-matrix tool selection — when a 2nd tenant/process needs it. (Maintain seams, defer machinery.)

---
## PRIORITY — UI is now a blocker (elevated from deferred polish)
The dashboard is not usable for evaluation (confirmed via dry run). Treat UI quality as on par with architecture.

**Functional bugs (correctness, fix first):**
- "Open gate" not bound to the active tab/stage → opened `final_review` on the Topics tab ("no APPROVED_ASSIGNED" error). Each tab must open ONLY its stage's gate for the selected round.
- No round scoping — Scripts tab showed R1's 56 while the dry run is R2's 5. Add an explicit round selector; scope every tab to selected round + its stage.
- No action feedback — change comments left no visible trace; show approvals, where a comment went, and the resulting revision (v2).

**Interim language:** switch UI chrome to **English-only** via the existing i18n layer (cheap locale flip — no rewrite). CONTENT stays bilingual (topics/hooks/scripts/justifications/comments). Arabic UI + language switch = later deliberate pass.

**Proper redesign (not a patch), reference patterns:**
- Components: **shadcn/ui + Tailwind (Radix)** on the existing Next.js.
- Review UX: GitHub PR review + Linear (clear status, fast, legible).
- Co-creation feel: ChatGPT Canvas / Claude Artifacts / Cursor (side-by-side content, accept/reject, revision/diff view).
- Conversational/agentic: bring the M6 copilot/twin in as a side-panel (what makes it dynamic, not a flat form).
- Engine stays single source; don't reinvent — adopt proven libraries/patterns.

**Unblock content eval independent of the dashboard:** export round/topic state to `samples/` (clean markdown) or use Telegram digest, so content can be judged while the UI is rebuilt.

### Agentic-UI references for the redesign (study, don't reinvent)
Our architecture already matches current best-practice agentic-UI patterns — the UI just needs to express them.
**Borrow from:**
- **Magentic-UI** (Microsoft, OSS) — HITL agentic web UI: co-planning, co-tasking, action guards. Closest reference.
- **CopilotKit / Generative UI** — embeddable agent copilot side-panel for React/Next (accelerates M6 + conversational feel).
- **Microsoft AG-UI** — in-app HITL approval-event pattern.
- **LangGraph + LangSmith** — branching HITL control + trace observability (gate engine + M7).
- Plus: GitHub PR review (approve/request-changes/inline), Linear (clean status/keyboard), ChatGPT Canvas / Cursor (side-by-side content + accept/reject + diff). Base: shadcn/ui + Tailwind.
**Patterns to implement (map to what we already designed):**
- Command surface (copilot/command palette); planning visibility; tool-use disclosure; memory surfacing; workflow tracking; recovery routing.
- "Approve like a teammate, not a debug console" = our topic justification + review disposition (what/why/risk, concise).
- Tiered approval by risk = our autonomy levels + hard floors.
- Override (pause/veto/rollback) as PRIMARY actions = our human-override + escalate/waive.
- Live telemetry + multi-agent coordination view = M7 living-operation.
Verify versions/compat (context7) before adopting any library.

---
## CONCEPT (evaluated) — graph as a unifying VIEW + model (not the transactional store)
The system is already a graph: items/agents/stages/decisions = nodes; transitions = edges; revisions = interim nodes; audit_log = an edge list; methodology + capability matrices = graphs.

**Adopt the graph as a derived VIEW + mental model over the existing relational + state-machine core.** Project from data we already have (slots, transitions, audit_log, principals). Do NOT rewrite the approval engine as a graph DB — gates/slot_status give ACID, deterministic, auditable state with hard guards (that's correctness, not friction; bare graph weights would weaken invariants/audit).

**Where the graph wins (build as projections):**
- M7 living-operation **control graph** (agents/items/flows, bottlenecks, handoffs).
- **Methodology coverage & theme insight** (InfraNodus-style: clusters, gaps, under-covered HCS/lenses, influential themes) — feeds the strategy/analytics loop.
- **Provenance/lineage** of any item/decision (ties to attribution/audit).
- Revisions/change-requests as interim nodes (view over revision history).

**Discipline:** define edge-weight SEMANTICS per use-case (flow volume, approval/reject rates, time-in-stage=bottleneck, similarity, autonomy/confidence) — no vague pretty weights.

**Honest scope of "less friction":** true for visualization/insight/lineage/traversal queries; NOT for the transactional core (keep explicit state + guards).

**Tooling:** react-flow / Cytoscape.js for the operational/control graph (pairs with shadcn/Next; n8n itself validates workflow-as-graph); sigma.js/D3-force + InfraNodus inspiration for insight/coverage. Storage: stay relational + pgvector; if traversal queries justify it later, prefer Postgres-native graph (Apache AGE) / recursive SQL before a separate graph DB.

**Sequencing:** don't divert the current Topics UI rebuild. Graph view = M7/insight layer. Cheap now: pick react-flow as the intended tool so the UI anticipates it; keep event/attribution data clean (it's what the graph projects from).

---
## OVERARCHING FRAME — event-sourced temporal graph + state machine = the platform as memory
The platform (and later the org) is ONE thing seen three ways:
- **State machine** = dynamics (valid transitions; the gates).
- **Graph** = structure (a snapshot of nodes/edges/weights at any instant).
- **Event log** = history; any past graph snapshot is DERIVABLE by replay. The event history IS the organization's MEMORY (episodic: what/when/who via attribution; semantic: embeddings over decisions/content/outcomes — topic ledger is the seed).
Unifies: gates, graph view, audit/attribution, analytics, and copilot/agent memory ("what did we decide / what worked / why").

**Refinement (avoid over-build):**
- Do NOT do full event-sourcing/CQRS now. Use DUAL representation: relational tables = current-state read model (transactional/correct); append-only event log = history/memory/graph-projection. (audit_log + attribution is ~80% there — make it first-class & complete: type, actor, before/after, payload, time, tenant.)
- DERIVE snapshots by replay (+ optional materialized checkpoints for perf); don't hoard full snapshots.
- Memory must be structured to be useful: define the questions it answers; add index + semantic layer (extend embeddings from topics to decisions/outcomes). Raw log != memory.
- Govern memory: retention, access (IAM/principals), tenant scoping.

**Adopt NOW (one cheap seam):** treat the event log as first-class, complete, well-structured, with clean attribution — this makes the temporal graph, snapshots, memory, M7 "rewind," and a smarter copilot all derivable later instead of a rewrite.
**Defer:** replay infra, temporal-graph store, CQRS, bitemporal modeling — until queries/scale demand.
**No diversion now:** Topics UI rebuild proceeds; this is a modeling frame + one data discipline.

### Content refinements from R2 review (fold into writer later — non-blocking)
- Extend the dialect guard to the **justification/rationale** field (leaked دلوقتي / ده); also sharpen the rationale prompt — currently a bit boilerplate ("many people struggle with X").
- Rework should be **surgical for minor edits** (a word-swap comment shouldn't regenerate the whole hook). Add a "minor-edit vs rethink" distinction so small comments preserve unchanged parts.
- Governing frame is now stated explicitly in **ARCHITECTURE.md** (read alongside this file).

### Local GPU nodes — RTX 3090 (back online) + RTX 6000 (multi-node providers)
3090 (24GB): comfortably 7–14B; up to ~32B Q4 / Qwen3.x-35B-A3B MoE; load any GGUF via Modelfile. QLoRA feasible (7B afternoon, 13B overnight; Unsloth 2–5× faster, ~500+ examples → custom model in hours).
Roles (priority):
1. **LoRA training node = the real win** — fine-tune a 7–13B Arabic base (Falcon-H1 Arabic / ALLaM / Qwen) on Moataz's ~1,400-caption corpus (instruction pairs) via Unsloth → private, free, authentic-Moataz voice model. Beats generic bigger bases for THIS task. Feasible now (no need to wait for RTX 6000).
2. **Local writing-model node** — serve via Ollama as a provider node (free/private fallback or bulk scripts). Bake-off: Qwen3.x 14B/27B, Gemma4 12B/26B-A4B, Falcon-H1 Arabic, ALLaM, Shahin. Caveat: 24GB local = "good not frontier" for generic Arabic; LoRA is the quality path.
3. **Media/ASR node (Phase 2/3)** — Whisper large-v3 (Palestinian transcription); image/video gen (Flux/SD) for carousels/B-roll.
Tooling: **Ollama = serving** (headless daemon, OpenAI-compatible :11434, remote) → provider-registry node; **LM Studio = experimentation/bake-off** (GUI; serves only while open; LM Link/Tailscale for remote). Expose Ollama OLLAMA_HOST=0.0.0.0 + base_url = Windows LAN IP:11434 (or Tailscale). RTX 6000 = bigger-model/heavier-training tier. All config-driven (no-hardcode) — just registry entries.
Sequencing: don't divert the UI rebuild. Parallel/next: (a) Ollama-as-service on 3090 as provider node + Arabic bake-off; (b) prep the LoRA dataset from the corpus (highest-value future task).

### Notes — copilot shell & UX trajectory (from rebuilt-UI review)
- **CopilotKit is INTERIM, not a foundation.** It deblocks the dry run + seeds M6, but it's a vendor surface (its own dev/marketing chrome). Keep it behind a clean, swappable boundary: the copilot calls ONLY our gate engine via our tool/API contract; no CopilotKit-specific assumptions in the core. M6 proper copilot (our own / user's twin via MCP) must be a drop-in replacement; drop CopilotKit chrome from production UI. Don't lock in early.
- **UI/UX still far; serious redesign is later AND is discovery/hardening, not just polish.** Expect the deep UX pass to REVEAL latent gaps in state/data-model/flow that the current flat UI hides — budget engine/data fixes as part of it. (Functional topic-review now works end-to-end on :3007 — correctness bugs fixed; rebuilt on shadcn/Tailwind v4.)

---
## ROADMAP (refined) — stage-as-uniform-contract; v1 = full lifecycle w/ consistent gates
Insight: approval machinery is GENERIC; stages differ only by artifact type + actors. A manual stage = a gate with no AI generator.

**Stage = { input artifacts, GENERATOR, output artifacts, review gate, actors/roles, directives }.** Generator is pluggable:
- ai = topic/script (built); manual = production/edits/distribution (now); external = Agentic Video Producer (later), via the stage contract.
Define input/output/directive contract for EVERY stage now, consistently → AVP/POSTIZ/AI plug into the generator slot later without touching the engine. Review card generalizes to any artifact (only the preview differs).

**Add now as MANUAL gates (reuse engine + review card; cheap):**
- Production (physical): confirm shoot done + upload raw cuts/images → approve → flow on.
- Media-edit: upload edits → review/approve (per-edit/batch), media review card. DEFINE the AVP integration contract here (in: approved script + production directives + raw assets; out: edit options → review gate).
- Distribution: mark formatted/published per platform (manual now; POSTIZ later). [scope call — recommended IN for end-to-end completeness]
- **Minimal DAM/asset model** (the one new piece): store/reference raw+edited media, linked to slot, with versions + platform variants.

**v1 (refined) = complete content lifecycle** (idea→topic→script→production→edit→format→publish→analytics) with consistent gates, AI where ready + humans filling manual stages; each manual stage is a labeled slot for future automation. Stronger than "content brain only."

**Roadmap order:** (1) finish M5 functional dry run; (2) M9 = stage generalization + manual production/edit/distribution gates + minimal DAM + AVP/POSTIZ contracts; (3) post-v1 plug-ins into the seams: AVP (edit generator), POSTIZ (distribution), AI production directives, M6 copilot, 3090 node+LoRA, serious UX pass, M7 graph/living-op, M8 IAM, analytics loop.
**Next move:** finish M5 dry run → then CC work order for M9.

### External integrations — providers plugged into the same gate/review spine
Platform = orchestration + approval + memory spine; specialized work = external capability providers via defined contracts (API/MCP). Gate/review structure is uniform across all.
- **Agentic Video Producer (AVP)** → media-edit stage generator (in: approved script + production directives + raw assets; out: edit options → review gate).
- **POSTIZ** → distribution executor behind the publish gate (format/schedule → approve → POSTIZ pushes at 09:00/20:00 UAE). Nothing publishes without passing its gate.
- **User's analytics system** → INTERFACE, don't rebuild. Analytics Repo = ingest + normalize + insight layer over their system → feeds Strategy/Planner. Analytics-driven outputs (new strategies / methodology amendments) are PROPOSALS that pass a review gate before applying — high-stakes → hard-floor human gate (AI proposes, human approves; never silent methodology rewrite). Same propose→review→approve pattern.
- Register each as a provider/tool node (capability matrix). Define contracts as stable seams in M9; integrations are post-v1 plug-ins.

### Backlog (deferred, cheap) — user-editable aliases for actors/agents/departments
Half-seeded: principal table already has bilingual display_name_ar/_en; engine references STABLE IDs, not names. Add:
- User-editable **aliases / display names** (admin/settings, M8) for principals (AI agents, agent reps, users) and extend to departments/modules (and optionally stages). Per-tenant; bilingual.
- Discipline (already honored): **stable internal ID ≠ display alias** — code/contracts/events/graph reference the immutable ID; UI renders the editable alias, so renaming is always safe (no coupling).
- Powers UI/UX personalization + the living-operation map (named nodes) + copilot ("approve Hermes's drafts"). Deferred; lands with M8/settings + the UX pass.
