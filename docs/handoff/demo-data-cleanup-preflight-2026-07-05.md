# Demo-Data Cleanup Preflight (2026-07-05)

Author: CC (read-only preflight; **no DB mutation**)
Prompt: "Demo Data Cleanup Preflight — CC only (OR)"
Status: **PLAN ONLY — nothing deleted. Awaiting explicit mutation authorization.**

---

## ⚠️ Headline: the candidate assumption is stale

The directive scoped candidates as `R54`, `R55`, `R2–R53`. The **live DB actually holds 89 rounds** (`R1–R83` + 6 e2e-tenant fixtures) and **8,994 slots**. `R55` alone is **8,784 slots (97.7% of all slots)**. There are also **R1 and R56–R83** (29 rounds) of identical test-clutter nature that are **outside the authorized candidate list** — a "clean" demo would still show them. They are flagged below but **not** prepared for deletion in this directive.

---

## 1. DB identity

| Field | Value |
|-------|-------|
| Container | `tanaghom-db` (`pgvector/pgvector:pg16`) |
| Host port | `0.0.0.0:5433 → 5432` |
| Database / user | `tanaghom` / `tanaghom` |
| App connection | gate API (`tanaghom-gateapi`) → `DB_HOST=db DB_NAME=tanaghom`, `TANAGHOM_WRITER_STUB=1` |
| Environment identity | **Shared DEV DB, stub-writer mode** — not a production/client DB. All rounds are `tenant_id ∈ {default, e2e}`; none carries a distinct client/live tenant. |

**No production or client tenant exists in this DB.** Every round is a planner/validation/e2e artifact created 2026-07-04 → 2026-07-05 during the stabilization work.

## 2. Round inventory (89 rounds), grouped by family

| Family | Rounds | Slots | Topics | Scripts | Approvals | Decisions | Directives | Nature |
|--------|-------:|------:|-------:|--------:|----------:|----------:|-----------:|--------|
| **E2E-FIXTURE** (RE2E, RFIN, RPROD, REDIT, RDIST, RSCR; tenant=`e2e`) | 6 | 13 | 13 | 10 | 1 | 5 | 8 | Playwright harness fixtures |
| **R55** (`366-day run … 24/day`) | 1 | **8784** | 0 | 0 | 0 | 0 | 0 | #4 MAX-bounds validation |
| **R54** (`3-day run … 2/day`) | 1 | 6 | 0 | 0 | 0 | 0 | 0 | #4 bounds validation |
| **R2–R53** (`1-day run`, `refresh-stickiness`, `schedule-framework-chain`, `content-handoff-e2e`) | 52 | 123 | 132 | 37 | 33 | 158 | 165 | Automated e2e/test clutter |
| **R1** (`BrowserValidation_04`) | 1 | 6 | 9 | 0 | 0 | 6 | 9 | Browser-validation clutter — **out of candidate scope** |
| **R56–R83** (same `1-day run` / named-test patterns) | 28 | 62 | 64 | 18 | 18 | 80 | 82 | Same clutter — **out of candidate scope** |

Total accounted: 6+1+1+52+1+28 = **89 rounds** ✓. **Zero rounds have any `slot_review` row** (no human review persisted anywhere) — the approvals/decisions/directives present are all from automated test flows (stub writer + auto-decide in specs).

### Dependency model (verified)
- Chain: `round → slot → {topic, script, slot_review, slot_approval, directive, gate_target, gate_decision, asset}`. `topic` also FKs `round_id` directly.
- **All FK delete rules are `NO ACTION` (no cascade)** → children must be deleted first, in order.
- `gate` / `gate_assignment` are **not** round-scoped (`scope='batch'`, shared per-stage; 181 gates total) → **untouched** by round cleanup; only slot-linked `gate_target`/`gate_decision` rows are removed.
- No persisted `job` or `schedule` table — generation jobs are the ephemeral in-memory `/jobs` registry; schedules live in `round.post_times` (jsonb) + slot rows (removed with their round).
- UI has no server-side "default round" — the dashboard persists the selected round in `localStorage`/URL only. **The only rounds the automated suite depends on are the 6 `tenant=e2e` fixtures.**

## 3. Safety classification

| Group | Classification | Rationale |
|-------|----------------|-----------|
| **R55** | **SAFE_TO_DELETE** | Pristine sacrificial #4 MAX-bounds test: 8,784 slots, **zero** downstream artifacts. Single biggest win. |
| **R54** | **SAFE_TO_DELETE** | Pristine sacrificial #4 bounds test: 6 slots, zero children. |
| **R2–R53** | **SAFE_TO_DELETE** | Proven sacrificial: mechanical test labels, tenant=`default`, created in a tight 2026-07-04 test cluster, **zero human `slot_review`s**; carries only automated stub/decide children (removed in order). |
| **RE2E, RFIN, RPROD, REDIT, RDIST, RSCR** | **DO_NOT_DELETE** | `tenant=e2e` Playwright harness fixtures — deleting them breaks the e2e suite (the release gate). |
| **R1, R56–R83** | **OUT_OF_SCOPE (UNKNOWN_STOP for this directive)** | Same sacrificial nature as R2–R53, but **not in the authorized candidate list**. Not prepared for deletion here. Recommend a separate explicit authorization to include them, else the demo still shows 29 clutter rounds. |

## 4. Read-only inventory SQL (re-verify anytime)

```sql
-- identity
SELECT current_database(), current_user;
-- family footprint (same query used for §2)
WITH fam AS (
  SELECT s.round_id, r.tenant_id,
    CASE WHEN r.tenant_id='e2e' THEN 'E2E-FIXTURE'
         WHEN s.round_id IN ('R54','R55') THEN s.round_id
         WHEN s.round_id ~ '^R([2-9]|[1-4][0-9]|5[0-3])$' THEN 'R2-R53'
         WHEN s.round_id='R1' THEN 'R1'
         WHEN s.round_id ~ '^R(5[6-9]|[6-7][0-9]|8[0-3])$' THEN 'R56-R83'
         ELSE 'OTHER' END AS family, s.slot_id
  FROM slot s JOIN round r ON s.round_id=r.round_id)
SELECT family, count(DISTINCT round_id) rounds, count(*) slots FROM fam GROUP BY family ORDER BY family;
-- guard: any human review anywhere? (expect 0)
SELECT count(*) FROM slot_review;
```

## 5. Proposed cleanup SQL — DRAFT (do NOT run without the mutation directive)

**Rollback insurance first** (full custom-format dump; restorable via `pg_restore`):
```bash
docker exec tanaghom-db pg_dump -U tanaghom -d tanaghom -Fc -f /tmp/pre_cleanup_2026-07-05.dump
docker cp tanaghom-db:/tmp/pre_cleanup_2026-07-05.dump ./backups/   # keep off-container
```

### Block 1 — R54 + R55 (pristine; biggest win) — treat separately
```sql
BEGIN;
WITH tgt AS (SELECT unnest(ARRAY['R54','R55']) AS round_id)
-- no slot-children exist for these, but run the ordered deletes defensively:
, del_children AS (
    DELETE FROM asset         WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM tgt)))
;  -- (repeat pattern per child table — see Block 2 for the full ordered set)
DELETE FROM slot  WHERE round_id IN ('R54','R55');
DELETE FROM round WHERE round_id IN ('R54','R55');
-- verify, then:
-- COMMIT;  (or ROLLBACK; to abort)
```

### Block 2 — R2–R53 (test clutter; ordered child deletes required, NO cascade)
```sql
BEGIN;
-- resolve target rounds once
CREATE TEMP TABLE _tgt AS
  SELECT round_id FROM round
  WHERE round_id ~ '^R([2-9]|[1-4][0-9]|5[0-3])$' AND tenant_id='default';
-- 0) publication truth FIRST (added 2026-07-11, migration 022 / #200): publication rows FK
--    slots/gates/assets with NO ACTION and are delete-protected by guard triggers. A reset that
--    removes rounds MUST purge their publications first, inside THIS transaction, so the trigger
--    disable/enable and the deletes commit or roll back together (never left disabled):
ALTER TABLE publication_event     DISABLE TRIGGER trg_publication_event_immutable;
ALTER TABLE publication           DISABLE TRIGGER trg_publication_frozen;
ALTER TABLE publication_raw_asset DISABLE TRIGGER trg_publication_raw_asset_frozen;
DELETE FROM publication_raw_asset WHERE publication_intent_id IN
  (SELECT publication_intent_id FROM publication
    WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt)));
DELETE FROM publication_event WHERE publication_intent_id IN
  (SELECT publication_intent_id FROM publication
    WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt)));
DELETE FROM publication WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
ALTER TABLE publication_raw_asset ENABLE TRIGGER trg_publication_raw_asset_frozen;
ALTER TABLE publication           ENABLE TRIGGER trg_publication_frozen;
ALTER TABLE publication_event     ENABLE TRIGGER trg_publication_event_immutable;
-- 1) slot-children (order-independent among themselves)
DELETE FROM asset         WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
DELETE FROM directive     WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
DELETE FROM gate_decision WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
DELETE FROM gate_target   WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
DELETE FROM script        WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
DELETE FROM slot_review   WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id IN (SELECT round_id FROM _tgt));
-- 2) topic (FKs both round_id and slot_id) → delete by round_id covers all
DELETE FROM topic         WHERE round_id IN (SELECT round_id FROM _tgt);
-- 3) slot, 4) round
DELETE FROM slot          WHERE round_id IN (SELECT round_id FROM _tgt);
DELETE FROM round         WHERE round_id IN (SELECT round_id FROM _tgt);
-- verify expected counts (52 rounds, 123 slots) then COMMIT; else ROLLBACK;
```

**Verification inside the transaction before COMMIT** (numbers must match §2):
```sql
SELECT (SELECT count(*) FROM round) AS rounds_left, (SELECT count(*) FROM slot) AS slots_left;
-- expect rounds_left = 89 - deleted; e2e fixtures (6) + R1 + R56-R83 must remain
SELECT count(*) FROM round WHERE tenant_id='e2e';  -- must still be 6
```

## 6. Rollback / snapshot strategy

1. **Pre-cleanup `pg_dump -Fc`** (Block above) — full restorable snapshot; copy off-container. Primary rollback.
2. **Transaction-wrapped deletes** — run each block in `BEGIN … <verify> … COMMIT`; abort with `ROLLBACK` if counts are wrong.
3. **Dry-run first** — run each block with `ROLLBACK` at the end (instead of COMMIT) and inspect the row counts; only then re-run with COMMIT.
4. **e2e-fixture guard** — after commit, assert `SELECT count(*) FROM round WHERE tenant_id='e2e' = 6` and run the Chromium pack once to confirm the suite still seeds/passes.

## 7. Exact next mutation directive to run (only if approved)

Recommended staging — **most caution, biggest win first**:
- **Step 1 (authorized candidates, pristine):** delete **R55 then R54** (Block 1). Removes 8,790 slots with zero child-table churn — the single highest-leverage, lowest-risk demo cleanup.
- **Step 2 (authorized candidates, clutter):** delete **R2–R53** (Block 2, ordered child deletes).
- **Step 3 (NEEDS SEPARATE AUTHORIZATION):** to actually reach a clean demo list, also delete **R1 + R56–R83** (same nature, currently out of scope). Do **not** run without explicit inclusion.
- **Never:** the 6 `tenant=e2e` fixtures.

Each step: `pg_dump` snapshot → `BEGIN` → ordered deletes → verify counts + `e2e=6` → `COMMIT`.

## 8. Process attestation

- **Read-only. No `DELETE`/`UPDATE`/`TRUNCATE`/`DROP`/migration executed.** All queries were `SELECT`/`information_schema` only.
- DB identity proven before inventory; no ambiguity.
- No GitHub mutation, no code edits, no commits, no push, no Pi.
- `#24` untouched and separate. Groq audit report not committed; `dashboard/.env.local` untouched.
- This handoff is **uncommitted** (no commit without separate authorization).
