# Tanaghom — Autonomous Content Department

Methodology-driven, human-in-the-loop content engine for **Moataz Mashal / Tanaghum**.
Local-first (Docker, runs on an RTX 3090 workstation), tool-agnostic build (Claude Code / Codex / other).

## Read first
- **`BUILD_STATE.md`** — living progress tracker. Any coding agent reads this first and resumes from the last checkpoint.
- **`docs/00_INDEX.md`** — top-level documentation index, including the canonical v1.0 change request and release-readiness report.
- **`docs/14_Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.md`** — canonical program evolution / change request / release-readiness source report; client deliverables are in `output/doc/`.
  - Current shared client/internal baseline: issue `1.2` dated `July 2, 2026`.
- **`docs/16_Release_Gate_and_Delivery_Control.md`** — active delivery-control rule for issue scoping, validation, demo readiness, and regression prevention.
- **`docs/01_Blueprint_v2.md`** — architecture & decisions.
- **`docs/02_Phase1_Build_Spec.md`** — what to build now (DDL, agents, gates, acceptance).
- **`docs/13_Codex_Network_Sandbox_Runbook.md`** — Codex DNS and sandbox troubleshooting for networked sessions.

## Layout
```
docker-compose.yml          local stack (Postgres+pgvector, Adminer, n8n, optional Ollama/GPU)
system_config.example.yaml  ALL tunable parameters (copy -> system_config.yaml)
db/init/schema.sql          database schema (auto-runs on first compose up)
deploy/stitch-vps/          VPS deployment scaffold (public-IP now, domain-ready later)
docs/                       blueprint, build spec, setup, calibration, analytics, test drive
methodology/canon/          CANON-010..015 (pillars, HCS, lenses, hooks, formats, calendar)
methodology/records/        42 HCS seed records (the content substance)
data/analytics_exports/     IG/FB/TikTok/YT exports (baselines + Phase 4)
```

## Quick start (M1 — Foundation)
1. Install Docker Desktop (WSL2 backend on Windows).
2. `cp system_config.example.yaml system_config.yaml` and `cp .env.example .env` (set DB_PASSWORD).
3. `docker compose up -d`
4. Open Adminer http://localhost:8080 and n8n http://localhost:5678 to confirm they're up.
5. Point your coding agent at this repo:
   > "Read BUILD_STATE.md and docs/02_Phase1_Build_Spec.md. Build the methodology loader that seeds CANON-010..015 and the 42 records into the DB. Bring up the stack, load the data, tick M1 in BUILD_STATE, and stop for review."
6. Browse the `pillar` / `hcs` / `lens` / `format` tables in Adminer — M1 done.

## Operational check
- Run `tools/dashboard-health-check.sh` to verify the local dashboard, gate API, and Tailscale Funnel target.
- Run `tools/dashboard-health-check.sh --fix-tailscale` to automatically repoint Funnel to the current dashboard port when it drifted.

## Principles (non-negotiable)
- All behavior tunable via `system_config.yaml` — no hardcoded parameters.
- Every stage is gated; nothing publishes without human approval; all transitions audited.
- Palestinian-dialect content needs native review; any Qur'an/Hadith needs scholar verification.
