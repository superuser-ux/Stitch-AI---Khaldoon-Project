# Demo-Data Cleanup — Execution Report (2026-07-05)

Author: CC (staged DB cleanup with snapshot + transaction guards)
Prompt: "Execute Demo Data Cleanup — CC only (OR)"
Preflight: `docs/handoff/demo-data-cleanup-preflight-2026-07-05.md`
Result: **SUCCESS — 89 rounds / 8,994 slots → 6 rounds / 13 slots. All 6 e2e fixtures preserved. Referential integrity clean.**

---

## 1. DB identity (re-confirmed before mutation)

| Field | Value |
|-------|-------|
| Container / image | `tanaghom-db` / `pgvector/pgvector:pg16` |
| Port | `0.0.0.0:5433 → 5432` |
| Database / user | `tanaghom` / `tanaghom` (PostgreSQL 16) |
| App connection | `tanaghom-gateapi` → `DB_HOST=db DB_NAME=tanaghom`, `TANAGHOM_WRITER_STUB=1` |
| Environment | Shared **dev** DB, stub mode. Tenants only `default(83)` / `e2e(6)` — **no production/client tenant**. |
| Pre-mutation counts | **89 rounds, 8,994 slots, 6 e2e fixtures, 0 human `slot_review`s** — matches preflight exactly. |

Identity matched the preflight → proceed authorized.

## 2. Rollback snapshot (created before any mutation)

| Field | Value |
|-------|-------|
| Method | `pg_dump -U tanaghom -d tanaghom -Fc` (custom format, restorable) |
| In-container path | `/tmp/2026-07-05_precleanup.dump` |
| Off-container copy | `…/scratchpad/2026-07-05_precleanup.dump` |
| Size | **1,052,684 bytes (1.05 MB)** — non-zero ✓ |
| Validation | `pg_restore -l` → **40 TABLE DATA entries** incl. `round`, `slot`, `topic`, `script`, `slot_approval`, `slot_review` — restorable ✓ |

Restore command if ever needed:
```bash
docker cp ./scratchpad/2026-07-05_precleanup.dump tanaghom-db:/tmp/restore.dump
docker exec tanaghom-db pg_restore -U tanaghom -d tanaghom --clean --if-exists /tmp/restore.dump
```

## 3. Stage-by-stage execution

Each stage: live pre-delete guard → `BEGIN` → in-transaction guard (`RAISE EXCEPTION` on any protected id / human review / wrong count) → ordered deletes (child rows → topic → slot → round; FKs are `NO ACTION`, no cascade) → `e2e=6` check → `COMMIT`. `ON_ERROR_STOP=1` throughout.

> **Note — first Stage-1 attempt was a proven no-op:** `docker exec` without `-i` didn't pass stdin, so psql ran nothing (exit 0, 0 rows changed). Post-stage verification caught it (R54/R55 still present); re-ran with `docker exec -i`. No data was affected by the no-op.

### Stage 1 — R55 + R54 (pristine bounds tests)
Guard: 2 rounds, both `default/planned`, 0 reviews, 0 protected, 8,790 slots.
Deleted rows: `slot 8790`, `round 2`; all child tables `0` (pristine). `e2e_left=6`.
After: **87 rounds, 204 slots.**

### Stage 2 — R2–R53 (automated test clutter)
Guard: exactly 52 contiguous rounds R2..R53, all `default`, 0 protected, 0 reviews, 123 slots.
Deleted rows: `directive 165`, `gate_decision 158`, `gate_target 262`, `script 37`, `slot_approval 33`, `topic 132`, `slot 123`, `round 52` (`asset 0`, `slot_review 0`). `e2e_left=6`.
After: **35 rounds, 81 slots.**

### Stage 3 — R1 + R56–R83 (owner-gated on live guard)
Live guard **passed the sacrificial proof**: 29 candidates, all `default`, 0 protected, 0 reviews, **all 29 labels matched known test patterns** (`N-day run`, `schedule-framework-chain`, `content-handoff-e2e`, `refresh-stickiness`, `BrowserValidation`). Owner condition satisfied → deleted.
Deleted rows: `directive 91`, `gate_decision 86`, `gate_target 144`, `script 18`, `slot_approval 18`, `topic 73`, `slot 68`, `round 29` (`asset 0`, `slot_review 0`). `e2e_left=6`.
After: **6 rounds, 13 slots.**

**Skipped candidates:** none — all three stages passed their guards and committed.

## 4. Final verification

| Check | Result |
|-------|--------|
| Total rounds | **6** |
| Total slots | **13** |
| e2e fixtures preserved | **6** ✓ |
| Protected ids present (RE2E/RFIN/RPROD/REDIT/RDIST/RSCR) | **6 / 6** ✓ |
| Non-e2e rounds remaining | **0** ✓ |
| Orphan slots (FK integrity) | **0** ✓ |
| Orphan topics (FK integrity) | **0** ✓ |

### Final round list (all preserved e2e fixtures)
| round_id | tenant | status | label | slots |
|----------|--------|--------|-------|------:|
| RDIST | e2e | planning | ops-distribution-e2e | 2 |
| RE2E | e2e | planning | e2e | 3 |
| REDIT | e2e | planning | ops-edit-e2e | 2 |
| RFIN | e2e | planning | final-e2e | 2 |
| RPROD | e2e | planning | ops-production-e2e | 2 |
| RSCR | e2e | planning | script-e2e | 2 |

**Totals removed:** 83 rounds (R1, R2–R53, R54, R55, R56–R83), 8,981 slots, and their generation artifacts (205 topics, 55 scripts, 51 approvals, 244 decisions, 256 directives, 406 gate_targets). Shared `gate`/`gate_assignment` (per-stage, `scope='batch'`) untouched.

## 5. Rollback notes

- Primary rollback: restore `2026-07-05_precleanup.dump` (§2) — captures the full pre-cleanup DB.
- Each stage was independently transaction-committed; no partial/aborted stage left dangling (integrity guards = 0 orphans confirm this).
- The `/jobs` registry is ephemeral (in-memory) and unaffected; no schema/migration change was made.

## 6. Recommended next action

- **Confirm the release gate still passes:** run the Chromium pack once — `cd dashboard && DASH_URL=http://localhost:3000 API_BASE=http://localhost:8009 npx playwright test --project=chromium` — to prove the cleanup didn't disturb the e2e fixtures (the suite reseeds `RE2E` per run and seeds the ops fixtures via `globalSetup`). Not run in this directive (no-validation-rerun discipline); recommended as the immediate follow-up. If any fixture seed is missing, restore from snapshot.
- The DB is now demo-clean: a reviewer opening the dashboard sees only the intended surface (no 89-round clutter list).
- Optional: delete the local snapshot once you're confident (`scratchpad/2026-07-05_precleanup.dump`), or archive it.

## 7. Attestation

- DB identity proven before mutation; snapshot created + validated before any delete.
- Only `DELETE` within transactions on the shared **dev** DB. **No `DROP`, `TRUNCATE`, migration, or schema change.** No production/client data (none exists).
- No protected `tenant=e2e` fixture deleted; no human-reviewed round deleted (there were none).
- No GitHub mutation, no code edits, no commits, no push, no PR, no label hygiene, no Pi, no security/key work.
- `#24` untouched. Groq audit report not committed; `dashboard/.env.local` untouched.
- This execution report is **uncommitted** (no commit without separate authorization).
