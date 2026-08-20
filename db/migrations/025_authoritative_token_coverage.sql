-- 025_authoritative_token_coverage.sql
-- #282 (#9 approval coverage, implementing #197's frozen contract via bound decisions D1/D3/D6) —
-- authoritative, principal-neutral, per-token ANY/ALL approval coverage.
--
-- ADDITIVE and NON-DESTRUCTIVE. Adds ONLY the operational state needed for:
--   • a gate-open snapshot that FREEZES the required assignment tokens and the eligible effective
--     principals per token (D3 — later membership changes never re-evaluate an open gate), and
--   • per-slot, per-token coverage records with the D1 distinctness invariants.
--
-- It does NOT backfill, classify, reinterpret, or mutate any existing gate/decision/audit row:
-- pre-existing gates carry NO snapshot here and therefore remain LEGACY by absence. It seeds/resets/
-- overwrites NO operator-owned policy or configuration.
--
-- Inspect-first, transactional, idempotent, and safe to rerun (every object guarded with
-- IF NOT EXISTS; the dependency check aborts — rolling back the whole transaction — rather than
-- partially applying). This repo has no migration ledger/runner; apply once with psql. A rerun is a
-- non-destructive no-op.

BEGIN;

-- Inspect-first: the base tables this contract references must exist, else abort (transaction
-- rolls back; nothing is partially applied). No legacy evidence is classified or touched.
DO $$
BEGIN
  IF to_regclass('public.gate') IS NULL
     OR to_regclass('public.gate_target') IS NULL
     OR to_regclass('public.slot') IS NULL
     OR to_regclass('public.principal') IS NULL THEN
    RAISE EXCEPTION '025 aborted: required base tables (gate/gate_target/slot/principal) are missing';
  END IF;
END $$;

-- (A) gate_snapshot — exactly ONE authoritative snapshot per authoritative gate, frozen at open.
--     Legacy (pre-migration) gates have no row here; legacy status is the ABSENCE of an authoritative
--     snapshot, never an inferred/backfilled classification.
CREATE TABLE IF NOT EXISTS gate_snapshot (
  snapshot_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  gate_id          uuid NOT NULL UNIQUE REFERENCES gate(gate_id) ON DELETE CASCADE,
  rule_key         text NOT NULL,                     -- frozen rule: 'any' | 'all'
  authoritative    boolean NOT NULL DEFAULT true,     -- true => per-token coverage governs resolution
  snapshot_version int  NOT NULL DEFAULT 1,           -- stable contract/version marker
  opened_at        timestamptz NOT NULL DEFAULT now(),-- frozen open-time
  tenant_id        text NOT NULL DEFAULT 'default',
  module           text NOT NULL DEFAULT 'content',
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT gate_snapshot_rule_ck CHECK (rule_key IN ('any','all'))
);

-- (B) gate_snapshot_token — the normalized required tokens for a snapshot. Equivalent/duplicate
--     tokens collapse to one (UNIQUE on the normalized identity), so duplicate assignment tokens
--     cannot inflate an ALL requirement.
CREATE TABLE IF NOT EXISTS gate_snapshot_token (
  snapshot_token_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_id       uuid NOT NULL REFERENCES gate_snapshot(snapshot_id) ON DELETE CASCADE,
  token_kind        text NOT NULL,                    -- user | role | group
  token_key         text NOT NULL,                    -- principal_id | role_id | group_id
  normalized_token  text NOT NULL,                    -- e.g. 'role:reviewer'
  CONSTRAINT gate_snapshot_token_kind_ck CHECK (token_kind IN ('user','role','group')),
  UNIQUE (snapshot_id, normalized_token)
);
CREATE INDEX IF NOT EXISTS idx_gate_snapshot_token_snap ON gate_snapshot_token (snapshot_id);

-- (C) gate_snapshot_eligible — the FROZEN eligible effective principals for each required token,
--     resolved once at gate-open. These rows are never touched by later membership changes (D3).
CREATE TABLE IF NOT EXISTS gate_snapshot_eligible (
  snapshot_token_id uuid NOT NULL REFERENCES gate_snapshot_token(snapshot_token_id) ON DELETE CASCADE,
  principal_id      text NOT NULL REFERENCES principal(principal_id),
  PRIMARY KEY (snapshot_token_id, principal_id)
);

-- (D) gate_token_coverage — per-slot, per-token authoritative coverage: exactly one covering
--     effective principal per required token per slot. This is the current maximum matching over
--     approving principals × frozen-eligible tokens, recomputed transactionally on each decision
--     change. The two UNIQUE constraints ARE the D1 invariants:
--       • UNIQUE (snapshot_token_id, slot_id) — a token is covered at most once per slot
--         (no duplicate coverage of the same token);
--       • UNIQUE (snapshot_id, slot_id, covering_principal_id) — one effective principal covers at
--         most one token per slot (no single principal covering more than one ALL token).
CREATE TABLE IF NOT EXISTS gate_token_coverage (
  coverage_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  gate_id               uuid NOT NULL REFERENCES gate(gate_id) ON DELETE CASCADE,
  slot_id               text NOT NULL REFERENCES slot(slot_id),
  snapshot_id           uuid NOT NULL REFERENCES gate_snapshot(snapshot_id) ON DELETE CASCADE,
  snapshot_token_id     uuid NOT NULL REFERENCES gate_snapshot_token(snapshot_token_id) ON DELETE CASCADE,
  covering_principal_id text NOT NULL REFERENCES principal(principal_id),
  decided_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (snapshot_token_id, slot_id),
  UNIQUE (snapshot_id, slot_id, covering_principal_id)
);
CREATE INDEX IF NOT EXISTS idx_gate_token_coverage_gate_slot ON gate_token_coverage (gate_id, slot_id);

-- (E) Relational PARENT-CONSISTENCY at the DB boundary (not only in engine code): a coverage row's
--     snapshot must belong to its gate, and its token must belong to that snapshot. Independent FKs
--     alone allow a misrouted/cross-parent insert that could corrupt ALL resolution, so enforce it
--     with composite parent identities + composite FKs (the D1 uniqueness constraints above are kept).
--     Added via guarded ALTERs so this is idempotent for BOTH a fresh and an already-applied local DB:
--     on fresh the tables were just created; on an already-applied DB the CREATEs above were no-ops and
--     these ADDs supply the missing constraints. Every guard is name+table scoped, so a rerun is a no-op.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='gate_snapshot_gate_snapshot_uq' AND conrelid='gate_snapshot'::regclass) THEN
    ALTER TABLE gate_snapshot ADD CONSTRAINT gate_snapshot_gate_snapshot_uq UNIQUE (gate_id, snapshot_id);
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='gate_snapshot_token_snap_uq' AND conrelid='gate_snapshot_token'::regclass) THEN
    ALTER TABLE gate_snapshot_token ADD CONSTRAINT gate_snapshot_token_snap_uq UNIQUE (snapshot_id, snapshot_token_id);
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='gtc_gate_snapshot_fk' AND conrelid='gate_token_coverage'::regclass) THEN
    ALTER TABLE gate_token_coverage ADD CONSTRAINT gtc_gate_snapshot_fk
      FOREIGN KEY (gate_id, snapshot_id) REFERENCES gate_snapshot (gate_id, snapshot_id) ON DELETE CASCADE;
  END IF;
END $$;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='gtc_snapshot_token_fk' AND conrelid='gate_token_coverage'::regclass) THEN
    ALTER TABLE gate_token_coverage ADD CONSTRAINT gtc_snapshot_token_fk
      FOREIGN KEY (snapshot_id, snapshot_token_id) REFERENCES gate_snapshot_token (snapshot_id, snapshot_token_id) ON DELETE CASCADE;
  END IF;
END $$;

COMMIT;
