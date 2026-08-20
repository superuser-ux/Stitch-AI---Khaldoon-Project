# Live Client Trial — Phase 1: Dedicated Trial Isolation Stack

Author: CC · Date: 2026-07-06 · `origin/main`: `30ccdc4` (unchanged — no code/PR)
Prompt: "Phase 1 — Build Dedicated Trial Isolation Stack — CC only (OR)"
Result: **SUCCESS — a dedicated, isolated, purgeable trial stack exists. Shared dev untouched. Writer mode is stub (Phase-1-acceptable). Client access NOT enabled (still blocked — see §7).**

---

## 1. Environment map

```
DEV   (untouched):   tanaghom_db `tanaghom`     <- gate API :8009 (tanaghom-gateapi)      <- dashboard :3000
TRIAL (new):         tanaghom_db `tanaghom_trial`<- gate API :8012 (tanaghom-gateapi-trial) <- dashboard :3001
```

Both databases live in the **same Postgres container** (`tanaghom-db`, pgvector pg16) but are **separate databases** — isolation is at the Postgres-database level, so trial operations cannot touch `tanaghom`. Both API containers share the `tanaghom_default` docker network and reach the DB via host `db`.

## 2. Trial DB identity + baseline seed

| Item | Value |
|------|-------|
| Database | `tanaghom_trial` (created `CREATE DATABASE tanaghom_trial OWNER tanaghom;` — did not touch `tanaghom`) |
| Schema | loaded from `db/init/schema.sql` (the full current schema, incl. CR01) → **40 tables** |
| Principals | **9** (seeded by `schema.sql`) — reviewer identities exist |
| Methodology | **pillar 5 / hcs 42 / content_format 4** — loaded via `loader/load_methodology.py` with `DB_NAME=tanaghom_trial` (writes only to trial DB) |
| Workflow config | **lazily auto-seeded** by `engine._ensure_workflow_seed` on first gate-open (verified path at `gates/engine.py:1181,2031`); not required pre-seed |
| Rounds / slots | **0 / 0** — clean, no dev/e2e clutter, no old rounds |

## 3. Round counts — isolation proof

| Stack | DB | Rounds |
|-------|----|-------:|
| Dev | `tanaghom` | **209** (unchanged before/during/after all Phase-1 work) |
| Trial | `tanaghom_trial` | **0** |

Verified at three layers: DB (`SELECT count(*) FROM round`), API (`GET :8012/rounds` → 0 vs `:8009/rounds` → 209), and dashboard (`GET :3001/gw/rounds` → 0). A client opening `:3001` sees an empty, clean round list.

## 4. Trial stack — how it was started (secrets redacted)

**Trial API container** (stub mode for Phase 1):
```bash
PW=$(docker exec tanaghom-gateapi printenv DB_PASSWORD)     # captured, never printed
docker run -d --name tanaghom-gateapi-trial --network tanaghom_default \
  -v /Users/Kay/Dev/tanaghom:/work -w /work \
  -e DB_HOST=db -e DB_PORT=5432 -e DB_USER=tanaghom -e DB_PASSWORD="$PW" -e DB_NAME=tanaghom_trial \
  -e TANAGHOM_WRITER_STUB=1 -e PYTHONPATH=/work \
  -p 8012:8000 \
  python:3.12-slim bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000"
unset PW
```
- `REVIEWER_PROXY_SECRET` is unset on both API and dashboard → both use the same default, so the dashboard's signed `x-principal-*` headers validate against the trial API. No secret handling required for that.

**Trial dashboard** (points at the trial API):
```bash
cd dashboard && API_BASE=http://localhost:8012 npx next start -p 3001
```

`GET :3001/gw/health` → `{"ok":true,"writer_stub":true,"writer_mode":"stub"}`.

## 5. Writer-mode status + exact Phase 2 live step

- Trial stack currently reports **`writer_stub: true, writer_mode: "stub"`** — Phase-1-acceptable (shared dev untouched, no live provider call made, no cost incurred).
- **Phase 2 to go live (trial only, no shared-dev impact):** restart the trial API container with `TANAGHOM_WRITER_STUB` **removed** and a valid live provider configured:
  ```bash
  docker rm -f tanaghom-gateapi-trial
  PW=$(docker exec tanaghom-gateapi printenv DB_PASSWORD)
  GROQ=$(docker exec tanaghom-gateapi printenv GROQ_API_KEY)   # or a dedicated trial key, out-of-band
  docker run -d --name tanaghom-gateapi-trial --network tanaghom_default \
    -v /Users/Kay/Dev/tanaghom:/work -w /work \
    -e DB_HOST=db -e DB_PORT=5432 -e DB_USER=tanaghom -e DB_PASSWORD="$PW" -e DB_NAME=tanaghom_trial \
    -e GROQ_API_KEY="$GROQ" -e PYTHONPATH=/work -p 8012:8000 \
    python:3.12-slim bash -lc "pip install -q ... && uvicorn gates.api:app --host 0.0.0.0 --port 8000"
  # then: curl :8012/health must show writer_stub=false, writer_mode=live
  # then: plan 1 round + run ONE generation to prove the live key works (this is the first real provider cost — needs owner OK)
  ```
  This requires **owner approval** (first real provider cost) and **confirmation the key is a valid, quota'd live credential** — I will not print it or run a live call without that approval.

## 6. Purge / reset plan (PROVEN against the trial DB)

Two levels, both trial-DB-only (cannot touch `tanaghom`):

**A. Selective round purge** (keeps baseline config — the Phase 2 reset path). Proven: planned `R1` (1 slot) → purged → 0 rounds, with pillar/hcs/principal baseline intact and dev still 209.
```sql
-- run with: docker exec -i tanaghom-db psql -U tanaghom -d tanaghom_trial
BEGIN;
-- optional dry-run: SELECT count(*) FROM round; SELECT count(*) FROM slot;
DELETE FROM asset         WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM directive     WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM gate_decision WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM gate_target   WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM script        WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM slot_review   WHERE slot_id IN (SELECT slot_id FROM slot);
DELETE FROM topic; DELETE FROM slot; DELETE FROM round;
COMMIT;
```
(Scoped by connecting to `-d tanaghom_trial`; deletes *all* rounds because the trial DB holds only trial data — no tenant filter needed, unlike shared dev.)

**B. Full nuke + rebuild** (disposability guarantee):
```bash
docker rm -f tanaghom-gateapi-trial
docker exec tanaghom-db psql -U tanaghom -d tanaghom -c "DROP DATABASE tanaghom_trial;"   # cannot affect tanaghom
# then re-run the §2/§4 create+seed+start sequence
```

**Snapshot (before any Phase 2 mutation):**
```bash
docker exec tanaghom-db pg_dump -U tanaghom -d tanaghom_trial -Fc -f /tmp/trial_precleanup.dump
docker cp tanaghom-db:/tmp/trial_precleanup.dump ./scratchpad/
```
(Not taken in Phase 1 — the trial DB is fresh/empty; snapshot becomes the first Phase-2 step.)

## 7. Remaining blockers for client access (NOT resolved in Phase 1 — by design)

1. **Live writer mode** — trial stack is stub; Phase 2 flips the trial container to live (owner approval + valid key, §5). No shared-dev impact.
2. **Client access / auth** — STILL OPEN. The trial dashboard `:3001` is the **same full operator surface** as dev: no login, no role scoping, admin routes (`/admin/methodology`, `/admin/workflows`), the planner, and persona switching all exposed. Handing a client `:3001` today = full admin power. Needs either the minimal **#13** persona/role login (client role hides admin) or a locked-down review-only build. **This is the gating blocker for actually giving access** and is Phase 3.

## 8. Recommended Phase 2 (proposed directive)

> **Phase 2 — Trial Live-Mode Enablement + Seed — CC only (OR).** With owner approval for first provider cost and confirmation the provider key is a valid live credential: (1) `pg_dump -Fc` snapshot the trial DB; (2) restart `tanaghom-gateapi-trial` with `TANAGHOM_WRITER_STUB` removed + provider key (no secret printed/committed); (3) verify `:8012/health` = `writer_stub:false, writer_mode:live`; (4) plan 1 realistic round and run ONE live generation to prove the key + capture output quality; (5) validate review → request-change → regenerate → approve on the trial stack; (6) leave the trial DB seeded with 1–2 clean live rounds; (7) report. Do NOT enable client access (Phase 3). Do NOT touch shared dev.

Then **Phase 3 — Client Access Boundary** (the #13/locked-down-build decision) before any credentials are shared.

## 9. Attestation

- Created: `tanaghom_trial` database, `tanaghom-gateapi-trial` container (:8012), trial dashboard (:3001). Loaded schema + methodology into the trial DB. Proved the selective purge.
- **Shared dev DB `tanaghom` untouched** (209 rounds before and after, verified repeatedly). **No e2e fixtures touched.** No dev API/dashboard restarted.
- **No secret printed or committed** — `DB_PASSWORD`/`GROQ_API_KEY` captured into shell vars and passed to `docker run`, never echoed; `.env*` untouched; no `git add`.
- **No live provider call made; no cost incurred** (trial ran in stub). No client access granted; no client credentials created.
- No code changes, no PR, no schema migration (schema loaded as-is). This report is **uncommitted**.
