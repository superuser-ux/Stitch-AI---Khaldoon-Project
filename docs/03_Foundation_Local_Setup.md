# Stage 2 · Foundation — Local Setup on Your Workstation (v1)

**Target machine:** Windows + RTX 3090, Docker Desktop (WSL2), used for dev.
**Goal of this step (M1):** get the stack running locally and load your whole methodology into a database you can browse — "the system knows your framework." No agents/UI yet; that's M2–M4.
**Build tools:** Claude Code / Codex / any — these files are tool-agnostic. Point your agent at this folder.

---

## 1. What runs where (your 3090 earns its keep)
| Job | Where | Why |
|---|---|---|
| Database, slots, methodology, dedup index | **Local (Docker, Postgres+pgvector)** | All data stays on your machine |
| Voice-critical writing (Topic, Script) | **Frontier API** | Best Palestinian-dialect quality — the brand voice |
| Embeddings (no-repeat dedup) | **Local on 3090** | Fast, free, private |
| Transcription of Palestinian audio (later) | **Local Whisper on 3090** | Free, private, strong |
| Image/video/music (Stage 3) | **Local on 3090 + some API** | GPU does the heavy media work |
| Glue/automation, Telegram, scheduling | **Local (n8n container)** | Visual, editable |

This honors your cost posture: pay only for the words that must be perfect; do the rest free on your GPU.

## 2. Your two requirements, built in
- **Flexibility:** everything tunable lives in `system_config.yaml` (calendar, distributions, post times, which model does which job, approval rules, dedup strictness). Change the file, not the code. Calendar is parametric — run a 28-day round, a different period, or inject ad-hoc posts.
- **Review everything:** every stage stops at a gate; nothing publishes without you; native-dialect + scholar reviews are mandatory flags; every change and approval is logged (audit trail). Config changes are themselves reviewable (keep the file in git).

## 3. The Foundation files (in this folder)
- `docker-compose.yml` — the local stack (Postgres+pgvector, Adminer DB viewer, n8n; optional Ollama for local models under a `gpu` profile).
- `system_config.example.yaml` — all your tunable parameters (copy to `system_config.yaml`).
- `BUILD_STATE.md` — the cross-agent progress tracker (solves reset limits — any agent resumes from here).
- Plus the source-of-truth docs: `Phase1_Build_Spec_v1.md`, `HCS_Records_All42_Seed_v1.md`, etc.

## 4. Do M1 — step by step
You (or your AI coding agent) run these on the workstation. Plain enough to follow; your agent can execute them too.

1. **Prereqs:** Docker Desktop running with WSL2 backend. (For local GPU models later: install NVIDIA Container Toolkit / WSL2 NVIDIA driver — not needed for M1.)
2. **Put the files in a folder**, e.g. `D:\tanaghom\`. Copy `system_config.example.yaml` → `system_config.yaml`. Create a `.env` with `DB_PASSWORD=...`.
3. **Start the core stack:**
   ```
   docker compose up -d
   ```
   Open **http://localhost:8080** (Adminer) and **http://localhost:5678** (n8n) to confirm they're up.
4. **Hand your coding agent this instruction:**
   > "Read `BUILD_STATE.md` and `Phase1_Build_Spec_v1.md`. Create `db/init/schema.sql` from the Phase 1 DDL. Write a loader that ingests CANON-010..014 and all 42 records from `HCS_Records_All42_Seed_v1.md` into the methodology tables. Bring up the stack and load the data. Then tick M1 in BUILD_STATE and stop for my review."
5. **What you'll see at the end of M1:** open Adminer → browse the `pillar`, `hcs`, `lens`, `format` tables → your full framework is there, 42 struggles and all. That's the "brain has a memory" moment.

## 5. After M1
We move to **M2 (the Planner)** — generate your first automatic 28-day plan and look at it. Each milestone in `BUILD_STATE.md` is a visible checkpoint you sign off before the next.

## 6. If a build session resets
No problem — the next agent reads `BUILD_STATE.md`, sees the last ticked milestone and the "Next action", and continues. Tell it: *"Read BUILD_STATE.md and continue from the next unchecked task."*

---
*Foundation v1. Tool-agnostic, local-first, fully parametric, review-gated — per your requirements.*
