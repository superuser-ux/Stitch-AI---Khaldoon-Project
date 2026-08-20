# Live Client Trial — Phase 2: Live Writer Proof & Trial Seed

Author: CC · Date: 2026-07-06 · `origin/main`: `30ccdc4` (unchanged — no code/PR)
Prompt: "Phase 2 — Live Writer Proof and Trial Seed — CC only (OR)"
Result: **SUCCESS — the isolated trial stack runs LIVE generation. One minimal live proof + a clean seed of 2 trial rounds. Review/regenerate/approve validated live. Shared dev untouched. Client access still NOT enabled (Phase 3).**

---

## 1. Snapshot (taken before any mutation)

| Item | Value |
|------|-------|
| Method | `pg_dump -Fc` of `tanaghom_trial` |
| Path | `…/scratchpad/trial_phase2_pre_2026-07-06.dump` (off committed paths) |
| Size | **113,295 bytes** — non-zero ✓ |
| Restorable | `pg_restore -l` → **40 TABLE DATA entries** ✓ |

## 2. Writer-mode flip — trial ONLY, proven live

Recreated only the `tanaghom-gateapi-trial` container **without** `TANAGHOM_WRITER_STUB` and with the provider key (captured into a shell var, never printed). Dev API container not touched.

| Stack | `/health` writer | DB |
|-------|------------------|----|
| **Trial :8012** | **`writer_stub:false, writer_mode:live`** ✓ | `tanaghom_trial` |
| Dev :8009 | `writer_stub:true, writer_mode:stub` (unchanged) | `tanaghom` |

Provider config: `system_config.yaml` `models.topic_hook/script` → Groq `meta-llama/llama-4-scout-17b-16e-instruct` (fallback `qwen/qwen3-32b`); key from `GROQ_API_KEY` env.

## 3. Minimal live-provider proof — SUCCEEDED

- Path: `POST /rounds/R1/stages/topic_review/generate` (round R1 = 1 slot, schedule pre-approved).
- Result: **200** `{"job_id":"4c1348d4…","total":1}`; slot `R1-D01-S1` moved `SCHEDULE_APPROVED → TOPIC_PROPOSED` in ~4–8 s.
- **Real generated hook** (Palestinian dialect, novel — NOT the stub's fixed hook): `قلقك مش بيديك شي، هو بيحكم عليك.` ("Your anxiety isn't in your hands — it rules you.")
- Groq key is valid and quota'd; no auth/402/429 error. (One earlier 500 was a *caller* mistake — I passed `topic` instead of the gate key `topic_review`; the provider was never reached. Corrected.)

## 4. Trial seed (after proof) — 2 clean, purgeable rounds

| Round | Label | Slots | State | Purpose |
|-------|-------|------:|-------|---------|
| R1 | `Client Trial — Live Proof 1` | 1 | `TOPIC_APPROVED` | the live proof + review-flow validation round |
| R2 | `Client Trial — Round A` | 3 | `TOPIC_PROPOSED` | **clean, un-reviewed client round** — 3 distinct live topics |

R2's three live hooks (all distinct, real): `خوفك مش حائط، هو باب` · `الحب مش بس شعور، هو قرار` · `أكيد في شي غلط معي`.

Naming is client-facing ("Client Trial —"), no `demo`/`test`/`e2e` labels. Topics only (no scripts pre-generated) — the client approves topics and generates scripts themselves, exercising forward progression at low pre-seed cost.

## 5. Live review-flow validation (on R1)

Full co-creation loop exercised against the **live** trial stack:
- **request-change** → `R1-D01-S1` → `CHANGES_REQUESTED` (200).
- **regenerate (live rework)** → `POST /rounds/R1/rework?stage=topic` → **v2 generated in 8.1 s**, feedback `خلّي الزاوية أوضح…` recorded on the new revision (the comment was injected as the rework directive — real live regeneration reflecting the reviewer note).
- **approve** → `TOPIC_APPROVED` (200).

So plan → schedule-approve → generate → request-change → regenerate → approve all work end-to-end on the isolated live stack.

## 6. Dashboard validation

- Trial dashboard `:3001` loads (200), `/gw/health` → `writer_mode:live`, `/gw/rounds` → **2 rounds only** (R1, R2) — **no dev/e2e clutter** (dev has 209).
- Generation-mode indicator: the #23 warning banner **correctly does NOT appear** in live mode (it only warns on stub/unavailable) — its absence *is* the "live" signal. (In Phase-1 stub mode it showed the "Generation: Stub" strip.)

## 7. Dev isolation proof (maintained throughout)

| Check | Value |
|-------|-------|
| Dev rounds | **209** (unchanged before/after all Phase-2 work) |
| Dev e2e fixtures | **6** (untouched) |
| Dev `/health` | `stub` (unchanged — dev writer never flipped) |
| Dev API/dashboard | not restarted |

## 8. Purge / reset — dry-run (selective, NOT executed)

Dry-run against `tanaghom_trial` only: **2 rounds / 4 slots** would purge; baseline **pillar 5 / hcs 42 / principal 9** survives. **Not executed** — the 2 clean client rounds are preserved. The selective FK-safe purge was already *proven by execution* in Phase 1 (seed → purge → 0, baseline intact, dev untouched). Reset commands are in the Phase-1 report §6.

## 9. Cost / risk notes

- **Live Groq calls made: 5 total** — 1 (R1 topic proof) + 3 (R2 topics) + 1 (R1 regenerate). Model `llama-4-scout-17b`; each a single short topic generation. Minimal, bounded — no batch/script generation, no broad volume.
- No provider errors, no quota/billing warnings. The key works.
- Trial container stays live; leaving it running costs nothing until generation is invoked.

## 10. Remaining blocker → Phase 3 (client access boundary)

**Unchanged and still gating:** the trial dashboard `:3001` is the **same open operator surface** — no login, no role scoping, admin routes (`/admin/methodology`, `/admin/workflows`), the planner, and persona switching all exposed. **Handing a client `:3001` today = full admin power over the trial data.** This must be resolved before any client access.

**Phase 3 options:**
1. **Minimal #13 client role** — a persona/login surface where a `client` role sees review-only (admin routes + planner hidden).
2. **Locked-down review-only build** — a trial dashboard build with admin routes/planner removed and a fixed reviewer principal, served behind the funnel.
3. **Reverse-proxy gate** — basic-auth in front of `:3001` (limits *who* connects, but does not hide admin controls from the authenticated client — weakest).

Recommendation: **Option 1 or 2** (they actually hide admin power); Option 3 alone is insufficient.

## 11. Attestation

- Snapshot taken before mutation; live flip on the **trial container only**; dev API/dashboard/DB untouched (209 rounds, stub, throughout).
- **No secret printed or committed** — `DB_PASSWORD`/`GROQ_API_KEY` captured into shell vars, passed to `docker run`, never echoed; config dumps masked key values; `.env*` untouched; no `git add`.
- Live provider calls limited to the minimal proof + small seed (5 calls). No e2e fixtures touched. No client access granted; no client credentials created.
- No code changes, no PR, no schema migration. This report is **uncommitted**.
