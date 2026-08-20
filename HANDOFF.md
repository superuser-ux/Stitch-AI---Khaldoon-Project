# HANDOFF — read this first

> **Canonical resume brief.** Read this file, then `BUILD_STATE.md` (milestone tracker). `docs/HANDOFF.md`
> is a pointer back here. The dated sections below the divider are **retained reference** (run/verify
> commands, hard constraints, architecture, design direction) — still accurate; the current snapshot is
> this top section.

## CURRENT HANDOVER — 2026-07-08 (post-#105 / #107 / #108 refresh)

### State — what's done & verified
- **Green baseline verified on 2026-07-07** on the running local stack:
  - `tsc --noEmit` (dashboard) — clean.
  - `docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest` — **ALL CHECKS PASSED**.
  - `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest` — **ALL API CHECKS PASSED**.
  - `cd dashboard && DASH_URL=http://localhost:3000 API_BASE=http://localhost:8009 npx playwright test --project=chromium` — **113 passed (6.5m)**.
- **Workflow in use = the directive bus.** Work arrives as GitHub issues labeled `directive:approved`
  (posted by a Custom GPT, `agent:gpt`). The agent ACKs (relabels `directive:running`), branches,
  implements, opens ONE focused PR with the active executor provenance, and **holds at the human merge
  gate** — never self-merges. After the human merges, the agent syncs `main`, relabels the issue
  `directive:done`, deletes the branch, and reports. See the memory note "Directive bus".
- **Merged on `main` this session (all squash-merged, green):** #92 Arabic/RTL card polish (#91/#54),
  #94 framework-on-cards (#50), #97 review-feed **sorting** (#16), #99 review-feed **text search** (#16),
  #101 observe-only demo-safe preflight (#100), #105 review-feed **pillar + content-format filters** (#104),
  and #107 demo-safe preflight **`--json` mode** (#106); plus earlier #73/#75/#82 (M7 provenance read-model
  + viewer + graph canvas, #71), #79 directive-bus governance (#78), #86/#88/#90 (approve-assertion +
  content-format reconcile + api_selftest fix, #84/#87/#89), and #77 flake stabilization (#76).
  The review feed now has outcome filtering, text search, sorting, pillar filtering, content-format
  filtering, `#49` content-ID lookup, `#93` framework surfacing, and `#91` Arabic/RTL readability.
  For #5, the observe-only demo-safe preflight plus JSON mode are both landed on `main`. These are docs/
  tools slices only, so the green baseline above still holds.

### Current board posture
- **No open PRs** at this refresh point.
- **#108** completed a read-only post-#107 planning scan and recommended this docs refresh as the safest
  next slice because the resume/build-state chain had become stale.
- The old quick-win queue from #103 is now exhausted: its two implementation-ready recommendations became
  #104 / PR #105 and #106 / PR #107.
- **Do not treat an implementation stream as preselected from this file.** After this refresh, the next
  implementation directive should come from fresh backlog inspection and live GitHub state, not from stale
  pre-#105 / pre-#107 recommendations.

### Branch map (all pushed to origin as of 2026-07-08 — nothing stranded)
| Branch | Where | Holds |
|---|---|---|
| `main` | this worktree baseline | all merged functional work incl. #101, #105, and #107; green |
| `feat/lunaris-redesign` | — | parked visual-redesign track (lunaris shell); pushed |
| `feat/ui-driven-runs` | — | parked Phase-1 UI-driven-runs branch (BUILD_STATE cites it); pushed |
| `feat/review-surface` | — | parked earlier review-surface checkpoint |
| `track-a/m9` | — | Track A / M9 v1-lifecycle (AVP integration contract) |
| `fix/planner-generation-guards` | worktree `../tanaghom-cr4` | planner generation-closure guards |
| `feat/telegram-pilot` | worktree `../tanaghom-telegram` | Telegram control-channel pilot (shares the DB) |
| `codex/telegram-control-integration` | worktree `../tanaghom-tg-integration` | Codex Telegram parity + bot selftest |

### How to resume (confirm green immediately)
1. Read this file, then `BUILD_STATE.md`, then `README.md`.
2. Ensure the stack is up (see "How to run" below): `tanaghom-db`, `tanaghom-gateapi`, dashboard on :3000.
3. Run the four green-baseline commands above; all must pass before making changes.
4. Pick up the directive bus: `gh issue list --label directive:approved --state open`. Execute per the
   protocol above (ACK → branch → implement → one focused PR → hold at merge gate).
5. If no directive is already approved, inspect the live backlog before selecting work. Do not resume the
   old #103 quick-win list blindly; it has already been consumed by #104 / #105 and #106 / #107.

### Environment prereqs NOT captured in the repo
- **Docker containers** on the `tanaghom_default` network: `tanaghom-db` (Postgres+pgvector, host **:5433**→5432),
  `tanaghom-gateapi` (host **:8009**→8000; **manual `docker run`, NOT compose** — see "How to run"),
  `tanaghom-bot` (Telegram; long-poll **singleton**), `tanaghom-adminer` (:8080), `tanaghom-n8n` (:5678).
  Dashboard runs on **:3000** (host process, not a container).
- **Secrets by NAME only** (never commit values): `.env` (gitignored) provides `DB_PASSWORD`, `GROQ_API_KEY`,
  Telegram bot token, `POSTGRES_PASSWORD`; `system_config.yaml` (gitignored; template = `system_config.example.yaml`).
  A **gitleaks pre-commit hook** (`.gitleaks.toml`) blocks secret commits.
- **Tailscale Funnel** exposes the dashboard publicly for demos (optional; observe with `tools/demo-preflight.sh`).

### DO NOT TOUCH (on this machine / repo)
- **`tanaghom-gateapi-trial`** container and **any client-trial data** — the isolated live-client-trial stack. Never read/write/mutate it.
- The **full-wipe reset** (`TRUNCATE`) of the shared Postgres — it destroys the parallel Telegram/other-worktree data. Only on explicit user call.
- **Other worktrees' working trees**: `../tanaghom-cr4`, `../tanaghom-telegram` (has 2 local untracked files: `.gitleaks.toml`, `dashboard/package-lock.json`), `../tanaghom-tg-integration`. Their branch tips are pushed; do not commit into their working dirs.
- **Unrelated local systems**: the self-hosted **Penpot** stack (`~/penpot_compose`, :9001) and its MCP runtime — not part of this repo.
- Preserve rounds **`R1`** (dry run), **`RE2E`** (e2e fixture), **`RTG1`** (Telegram) — clean only your own stray `R<n>` test rounds.

### Working-tree-only content (NOT committed — reported so it isn't assumed lost)
- **`artifacts/`** (~7.6M): `client-trial-guide/` + `operator-admin-guide/` (screenshots/guides, referenced by
  issue **#46**). **Now gitignored** (regenerable deliverables refreshed per #46 — kept out of git history
  to avoid compounding binary bloat; matches the repo's `output/`-style convention). A durable one-file
  snapshot exists **outside the repo** at `../tanaghom-artifacts-snapshot-2026-07-07.tar.gz` (6.6M gz).
  **Still on this machine only** — before a machine move, transfer that snapshot deliberately (it is
  **client** content: do NOT publish it to a public GitHub Release). Long-term home: fold finalized guide
  text into #46's tracked docs, keep raw screenshots external.
- **`ops/qa-scout/`**: local QA-scout scratch that **contains a live agent credential**
  (`…/.pi-home/.pi/agent/auth.json`). **Never commit.** Now covered by `.gitignore` on `main`.
- The 15 previously-untracked `docs/handoff/*.md` decision/audit notes are now preserved on `main`.

### Open items / next work
- **#16 status:** outcome filtering, text search, sorting, pillar filtering, and content-format filtering
  are already landed. Any further #16 slice should be selected from fresh product/operator scoping rather
  than the old "attribute filters next" note.
- **#5 status:** observe-only demo-safe preflight plus `--json` mode are landed. Any further #5 slice
  should be scoped freshly before implementation.
- **Next planning posture:** choose the next implementation directive from fresh GitHub backlog inspection
  after this docs refresh. There is no preselected next stream at this handoff point.
- Parked branches above are candidates to resume or prune (owner's call).

### Guardrails / invariants (load-bearing — do not violate)
- **Single source of truth:** this `HANDOFF.md` + `BUILD_STATE.md`. Don't fork a competing status doc.
- **Verification-first:** keep all suites green at every step; **preserve every `data-testid`**; browser-validate any surface change (not just builds/unit).
- **Never fabricate data as real** (no invented analytics — honest "connect analytics" empty state).
- **Config-driven, no hardcode** (tunables in `system_config.yaml`, mirrored to the example).
- **Agent hard floor:** the conversational agent proposes but **never commits a batch from free text**; commit stays human-confirmed + structured.
- **Directive-bus discipline:** one issue = one branch = one focused PR with executor provenance; no `git add .`; no secrets/`.env*`; hold at the human merge gate; never touch the trial container/data.
- **Version discipline:** before version-sensitive edits, verify the *installed* versions and check current docs / Context7 rather than assuming (repo runs exact Next 15.4.11 / React 19.0.0 in **both** frontend roots, pinned `pnpm@10.15.1` — not npm — for `dashboard/` and `workbench/` deps; Python 3.12 gate API). #297 upgraded both roots off the security-vulnerable Next 15.1.4 and pinned the package manager end-to-end, including the V1 Docker build — before that, `corepack enable` alone floated to registry-latest pnpm at build time.
- Commits end with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

# HANDOFF — earlier context (retained reference, 2026-07-04)

Continuity note for the next Claude Code session / agent / account. Pick up here with **zero regression**.

## 0. Claude Code operating brief (2026-07-04)
- **This is now a valid controlled handoff point.** The repo should be handed to Claude Code only on **scoped GitHub issues**, never as an open-ended "improve things" pass.
- **Mandatory working rule:** one issue = one implementation stream = one validation bundle = one GitHub comment with evidence.
- **Do not mix streams.** In this repo, drift/regression came mostly from combining review UI changes, workflow-admin changes, and planner/schedule changes in the same pass.
- **Before claiming anything ready, Claude Code must run browser validation on the affected surface**, not only builds or unit/API checks.
- **If a fix changes workflow semantics, Claude Code must validate both the API read model and the actual dashboard surface.**
- **If a task starts feeling like polish instead of closure, stop and log it instead of folding it into the active issue.**

### Recommended issue execution order for Claude Code
1. **`#3` Review surface hardening** — still the biggest source of user-facing friction and perceived instability. Keep this focused on correctness/consistency of per-item and selective batch behavior, not broad visual redesign.
2. **`#12` previous-stage summary retention after resolve** — treat as an adjacent stabilization item when it blocks clean progression through the pipeline.
3. **`#7` Calendar, numbering, and managed content-type operational alignment** — important for client-facing schedule-first flow and visible expectations.
4. **`#6` Workflow governance and admin-surface hardening** — safe next stream after surface stability and schedule alignment.
5. **`#5` Operational green preflight** — keep current localhost/Tailscale/Telegram checks documented and repeatable.
6. **`#8` Telegram control-channel hardening** — only in the separate Telegram worktree / branch at the right time; do not entangle with the main dashboard stream.

### Issues that are advanced enough not to reopen casually
- **`#2` Sacrificial rework validation:** real live topic + script rework evidence now exists. Remaining gap is interruption/resume simulation, not the core semantic rework loop.
- **`#4` Planner/content-type drift hardening:** backend and browser regression coverage now exist for incomplete/uneven managed weekly-count scenarios.
- **`#9` Approval semantics closure:** pending cards now surface remaining required approvers; focused approval browser validation is green.

### Stop conditions for Claude Code
- If it cannot keep the affected Playwright slice green, it should stop and report rather than layering more edits.
- If it needs to touch Telegram behavior, it should first confirm it is in the Telegram worktree, not this main dashboard stream.
- If it needs to change issue scope, it should open/log the scope split first instead of silently broadening the implementation target.

## 0. CR01 continuity note (2026-07-02)
- **`Full reset mode` is now defined operationally:** when the user asks for a full reset, clear only run-derived state (`round`, `slot`, `topic`, `script`, gates/approvals, directives/assets, `lens_history`, `hcs_cursor`, related run audit rows) and leave foundational/admin catalogues intact (`methodology*`, `workflow*`, `content_format*`, `format`, principals/roles/groups). Do **not** seed any new runs after this reset; the user starts from a blank slate.
- **Canonical readiness document added:** `docs/14_Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.md` is now the tracked source report for change request integration and release readiness; client `.docx` / `.pdf` outputs live in `output/doc/`. Start there for the latest consolidated status view.
- **Release-control runbook adopted:** `docs/16_Release_Gate_and_Delivery_Control.md` now defines the active delivery rule for this repo. Future work should follow: one issue = one acceptance target = one branch/worktree, with sacrificial validation and demo-safe preflight before anything is called ready.
- **Shared reference issue:** internal continuity notes and client-facing references are currently aligned to **issue 1.2 dated July 2, 2026**. Do not advance only one side; publish a new issue when the shared status baseline changes materially.
- **Current client-facing issue updated further:** the latest generated edition now uses softened client language, verified companion-system context for Analytics / SDAM / AVP, explicit note that the official Moataz analytics path is intentionally deferred, and a visual appendix with real screenshots where available plus placeholders where not.
- **Current alignment rule:** the active client `.docx` remains the distribution artifact, while the tracked support files (`docs/14_...md`, `docs/00_INDEX.md`, continuity notes, and `docs/assets/program_evolution_report_v1_0/`) must be kept synchronized to that same issue so internal and client references stay on one shared page.
- **CR01 approval/workflow implementation is now active in this worktree.** Foundation, approval-core, workflow-version backend, admin workflow surface, and the main operational approval visibility slice are implemented locally.
- **P6 foundation is now started too.** The repo markdown canon/records are imported into DB-backed `methodology_version` tables, the content-format registry is versioned, and the read-only admin route is `/admin/methodology`.
- **Operational UI verification is real, not only build-based.** Browser verification now works in Codex Desktop with full-access sessions, and the dashboard was rechecked after a full rebuild + `next start`.
- **Penpot MCP local runbook added:** `docs/design/PENPOT_MCP_LOCAL_SETUP.md` is now the canonical tracked note for the self-hosted Penpot + local MCP arrangement on this Mac. It records the Docker-hosted Penpot baseline (`http://localhost:9001`), the host-side MCP runtime (`4400`/`4401`/`4402`/`4403`), the `corepack` and `pnpm approve-builds` repairs needed on this machine, and the exact Penpot plugin prerequisites from the official docs.
- **Penpot MCP current state:** the mismatched npm `@penpot/mcp@stable` package (`2.15.4`) was replaced by a source-aligned runtime built from Penpot tag `2.16.2` at `/Users/Kay/.local/share/penpot-mcp/penpot-2.16.2/mcp`. Future agents should use that path first.
- **Penpot MCP launcher added:** use `/Users/Kay/Dev/tanaghom/tools/start-penpot-mcp.sh` as the preferred startup path. It prepares the aligned `2.16.2` source runtime and starts the MCP/plugin servers from the correct location.
- **Penpot MCP connection behavior:** host-side runtime and plugin UI were both verified. A real WebSocket handshake was observed on the server when the plugin showed `Connected`. The server also logged the connection closing later, which matches Penpot's documented requirement to keep the plugin UI open while MCP is in use.
- **Penpot reboot gotcha now confirmed:** after a system restart, Penpot can show `Bad Gateway` even with all compose containers `Up`. On this Mac, the durable fix was:
  - keep the same explicit `PENPOT_SECRET_KEY` on both `penpot-backend` and `penpot-exporter` in `/Users/Kay/penpot_compose/docker-compose.yaml`
  - if frontend nginx still points at a stale backend container IP, run `docker compose restart penpot-frontend` from `/Users/Kay/penpot_compose`
  - verify recovery with `curl -sS -D - http://localhost:9001/api/main/methods/get-profile` expecting `200 OK`
- **Important browser gotcha:** if the dashboard partially renders or loses client state, check for a stale Next asset set first. We hit a real `ChunkLoadError` from a stale `next start` process on port `3000`; the fix was `pnpm build`, then restart `next start`.
- **CR01 operational deep-link fix landed:** the `Overview -> My approvals -> Open` action now switches both **stage and round**. Before the fix, a pending approval from `RE2E` could open the current plan (`RTG1`) at the right stage but the wrong round.
- **Verified live path:** overview shows `Matched via` + `Required approvers`; opening the `RE2E` approval lands on `Plan RE2E` and shows the new `Your approval context` panel with acting assignments and required approvers.
- **Verified live methodology path:** `/admin/methodology` serves from the live dashboard, shows the active methodology seed counts (5/5/5/42), source-file digests, seeded platform registry, and the 7 content formats.
- **GitHub control map is now explicit:** issue `#1` governs release gate/process, `#2` sacrificial rework validation, `#3` review-surface stabilization, `#4` planner/content-type drift hardening, `#5` operational green preflight, `#6` workflow governance, `#7` calendar/content-type alignment, `#8` Telegram hardening, `#9` approval semantics / assignment closure, `#10` approval identity hardening, and `#11` the future `agent-first cowork surface` stream.

## 1. Where things stand
- **`main` (`origin/main`)** = all **functional** work merged & pushed: UI-driven runs (parametric planner, `POST /rounds`, generation jobs `/generate` + `/jobs`), `stage_state.next_action`, the **conversational agent endpoint** `POST /rounds/{id}/agent` (shared by dashboard + Telegram bot), themes/branding, gate-hygiene. All four suites green on main.
- **`feat/lunaris-redesign`** (branch off main) = the **visual redesign in progress**. Beyond the foundation/reskinned-Topics reference it now includes the **lunaris shell** (Overview / Workflow / Grid / Calendar lenses, responsive header/rail). A frontend race in `review-context.tsx` (new-run could let an older round/stage fetch overwrite the fresh selection) was fixed on **2026-07-01** by routing new-run through the guarded round switch + ignoring stale async `load()` responses. **All four suites green again.** ← *you are here.*
- **`feat/telegram-pilot`** = stream-3 (Telegram control-channel + bot agent), a separate worktree at `../tanaghom-telegram`. Do **not** disturb; it shares the DB.

Design so far renders correctly. The review surface (the screen the client had rejected) is reskinned to lunaris — see `docs/design/lunaris/03-reskin-topics.png`.

## 2. How to run (services — NOT docker-compose; the gate API is a manual container)
```bash
# Gate API (:8009) — for TEST SUITES you may enable the stub writer; for REAL runs do not.
docker rm -f tanaghom-gateapi >/dev/null 2>&1
docker run -d --name tanaghom-gateapi --network tanaghom_default -w /work \
  --env-file /Users/Kay/Dev/tanaghom/.env -e DB_HOST=db -e DB_PORT=5432 -e TANAGHOM_WRITER_STUB=1 \
  -v /Users/Kay/Dev/tanaghom:/work -p 8009:8000 \
  python:3.12-slim bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000"
# (drop `-e TANAGHOM_WRITER_STUB=1` for real topic/script generation and real rework.)

# Dashboard (:3000)
cd dashboard && (set -a; . ../.env; set +a; API_BASE=http://localhost:8009 npm run build) \
  && API_BASE=http://localhost:8009 npx next start -p 3000
```
- DB is `tanaghom-db` (pgvector) on the `tanaghom_default` network. `.env` + `system_config.yaml` are **gitignored** (secrets); GROQ key + DB password were rotated — the API loads them via `--env-file .env`.
- **Important stub nuance:** `TANAGHOM_WRITER_STUB=1` stubs the topic/script writer path broadly, including normal topic/script generation and rework. It is for deterministic test runs only; do not use it for real walkthroughs.

## 3. How to verify (keep ALL FOUR green at every stage)
```bash
docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest                                  # engine
docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest       # API (+agent §S, planner, jobs)
docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.lifecycle_selftest  # full chain
cd dashboard && DASH_URL=http://localhost:3000 API_BASE=http://localhost:8009 npx playwright test               # e2e (11)

- Health check:
  `tools/dashboard-health-check.sh`
  Use `tools/dashboard-health-check.sh --fix-tailscale` if the Funnel target drifted from the active dashboard port.
```
Notes: `lifecycle` occasionally reports 0 if run immediately after `api_selftest` (real-Groq rate-limit) — re-run it alone. The e2e reseeds the isolated **RE2E** round.

## 4. HARD CONSTRAINTS (do not violate)
- **No fabricated data shown as real.** Telegram/Instagram telemetry has **no integration yet** → render an honest **"connect analytics" empty state**, never invented numbers. This may be shown to the client.
- **Keep all four suites green** at every stage; preserve every `data-testid` through any reskin.
- **Do NOT run the full-wipe reset** (`TRUNCATE ...`). It clears the **shared** Postgres incl. stream-3's data. It waits until after the stream-3 Telegram walkthrough (the user will call it).
- **Preserve rounds `R1` (dry run), `RE2E` (e2e), `RTG1` (stream-3 Telegram).** You may clean your own stray `R<n>` test rounds surgically, never RTG1.
- **Agent hard floor:** the agent proposes but **never commits a batch from free text** (`allow_commit=False`); committing stays a structured, human-confirmed action.
- **Single generation mechanism:** the only way to generate is `POST /rounds/{id}/stages/{stage}/generate` (+ `GET /jobs/{id}`); the bot converges onto these. No parallel path.
- **Config-driven, no hardcode:** tunables live in `system_config.yaml`, mirrored to `system_config.example.yaml`.
- **Commits** end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. A **gitleaks pre-commit hook** blocks secrets (`.gitleaks.toml`).
- **n8n stays OUT of the approval path;** every stage is gated + audited; nothing publishes without human approval; nothing is destroyed (event-sourced).

## 5. Design direction (v2) — corrected + in progress
**Platform mapping (CORRECTED this session):**
- **Instagram = the publish target** (currently the only social platform). Distribution → an **IG feed-preview planner** (grid + calendar, drag-to-schedule); analytics = honest "connect Insights".
- **Telegram = a CONTROL / I/O channel** (NOT a publish target) — a second surface to approve / request-change / converse with the **Agent Rep**. Earlier mockups wrongly showed Telegram as a "published channel with subscribers/engagement" — **that framing belongs to Instagram; fix it.**

**The v2 vision (research-informed — agentic UX, infinite-canvas/tldraw, generative UI, IG grid-planners):**
- **One data model, many spatial lenses** — the same "cards" (topic/script/any approval component) shown as **List · Grid · Board · Calendar · Canvas (free/unpinned, draggable) · Workflow graph · IG feed preview**; instant switch, per-user. (Current build is *one fixed list view* — too rigid; make it responsive + flexible.)
- **Cards are fluid objects:** collapsible (chip ↔ compact ↔ full), collapsible **per section**, density modes, draggable, multi-select.
- **Agent Rep = a first-class OS layer**, not a side chat: ⌘K command bar, ambient "brief"/stand-up, acts on selection, can compose views (generative UI), transparency (planning/tool-use/undo), reachable on dashboard **and** Telegram. Autonomy hard-floor stays.
- Complementary ideas to develop: focus mode, presence/multiplayer on canvas, event-sourced **timeline scrubber** ("git for content" made visual), IG-native card previews, per-stage **autonomy dial**, sandbox/preview-before-commit.

**Where the design lives:** the Pencil source is **local only** (`~/.pencil/documents/.../pencil-lunaris.pen`). It contains the expected boards (`Tanaghom Overview`, `Workflow Graph`, `v2 — Agentic Content OS (vision)`) **plus extra local-only work not tracked in git**: a large `lunaris: design system components` board and exploratory `dashboard-utility` / `dashboard-revenue` / `dashboard-football` studies. As of **2026-07-01**, the local **`Workflow Graph` board was corrected** to the agreed platform model (Instagram = publish target, Telegram = control channel; no fabricated Telegram publish metrics) and the portable exports were refreshed from Pencil into `docs/design/lunaris/01-overview.png`, `02-workflow.png`, and `04-vision-agentic-os.png`. The portable references remain the **PNGs in `docs/design/lunaris/`** (`00-foundation-options`, `01-overview`, `02-workflow`, `03-reskin-topics`, **`04-vision-agentic-os`**) + this doc + the specs in `docs/superpowers/`. A different-machine agent works from those.

**Sync contract (NEW):** managed Lunaris design sync is now documented and enforced via [`SYNC_POLICY.md`](/Users/Kay/Dev/tanaghom/docs/design/lunaris/SYNC_POLICY.md), [`sync-map.json`](/Users/Kay/Dev/tanaghom/docs/design/lunaris/sync-map.json), [`sync-status.json`](/Users/Kay/Dev/tanaghom/docs/design/lunaris/sync-status.json), and the pre-commit guard [`tools/check_design_sync.py`](/Users/Kay/Dev/tanaghom/tools/check_design_sync.py). Any commit touching managed design-sensitive dashboard files or managed Pencil exports must also update `sync-status.json`.

## 6. Immediate next steps (the agreed plan)
The user chose: **implement what's locked → look live → then continue.** Foundation (stage 1 of 4) is done. Remaining before the user's live look:
2. **App shell + view-mode nav** (Overview · Workflow · Calendar · Board · Inbox/Canvas), wired to real round/stage state.
3. **Overview lens** (KPIs, schedule heatmap, live activity from `audit_log`, review queue, **IG** publish surface + honest empty analytics).
4. **Workflow lens** (stage nodes with live counts + actors; terminal node = **Instagram**, not Telegram).
Then **STOP for the live look** — the reskinned Topics/review surface is the real acceptance bar.
After that: the v2 flexible-workspace + agent-OS redesign (the user will also share their own design vision + a Pencil design they made).

## 7. Architecture pointers
- Engine (single source of truth): `gates/engine.py` (gate state machine, `stage_state`, directives, `_active_open_gate`). API: `gates/api.py`. Agent: `gates/agent.py` over `gates/contract.py`. Jobs: `gates/jobs.py`. Planner: `planner/plan_round.py` (`plan_round_api`, `scale_distribution`). Writer: `agents/run_writers.py`.
- Dashboard: `dashboard/lib/review-context.tsx` (state + engine calls), `dashboard/components/review/*` (app-shell, review-surface, review-item, stage-action, disposition-bar, new-run-dialog, theme-switcher), `dashboard/app/globals.css` (lunaris tokens), `dashboard/app/layout.tsx` (next/font).
- Continuity logs: `BUILD_STATE.md` (milestone-by-milestone), `docs/superpowers/specs|plans/*`.
