-- #423 — Immutable final-review target-package snapshots at attachment.
--
-- ADDITIVE, NO BACKFILL. Persists one immutable Stage-4 package-provenance snapshot per accepted
-- (gate_id, slot_id) at the moment a target is attached to a `final_review` gate (initial open,
-- open-reuse, or late reconciliation). Legacy targets attached before this migration simply have no
-- row and are read as typed `unknown_history` — nothing is inferred, backfilled, or rewritten.
--
-- Consistent with the repo's additive/idempotent/no-ledger convention: guarded with IF NOT EXISTS /
-- CREATE OR REPLACE, wrapped in one transaction, safe to re-run. Applied manually with psql.
--
-- Authority boundary: this evidence CONFERS NO AUTHORITY. It references the existing GATE-WIDE frozen
-- `gate_snapshot` (#282/025) via a composite FK; it introduces no target-level assignment snapshot and
-- re-resolves no role/group membership. The gate's frozen tokens, eligible principals, and ANY/ALL
-- coverage are untouched.

BEGIN;

CREATE TABLE IF NOT EXISTS final_review_target_package (
  gate_id                        uuid NOT NULL,
  slot_id                        text NOT NULL,
  -- the GATE-WIDE frozen snapshot this target inherits (never a per-target assignment freeze)
  snapshot_id                    uuid NOT NULL,
  round_id                       text NOT NULL REFERENCES round(round_id),
  -- selected, immutable lineage pinned from canonical records at attachment (never current heads)
  topic_id                       uuid NOT NULL,
  topic_revision                 int  NOT NULL,
  script_id                      uuid NOT NULL,
  script_revision                int  NOT NULL,
  -- the consumed configuration generation actually consumed, plus which canonical record proved it
  workflow_version_id            uuid NOT NULL,
  workflow_version_source        text NOT NULL,   -- 'script_provenance' | 'round_policy_snapshot'
  -- an existing production direction, recorded ONLY when actually present AND coherent at attachment
  production_directive_id        uuid,
  production_directive_revision  int,
  attached_at                    timestamptz NOT NULL DEFAULT now(),
  -- exactly one immutable snapshot per accepted (gate_id, slot_id)
  PRIMARY KEY (gate_id, slot_id),
  -- reference the EXISTING gate target membership (the pair must be a real target)
  FOREIGN KEY (gate_id, slot_id) REFERENCES gate_target (gate_id, slot_id),
  -- reference the EXISTING gate-wide frozen snapshot (parent-consistent composite FK, mirrors 025)
  FOREIGN KEY (gate_id, snapshot_id) REFERENCES gate_snapshot (gate_id, snapshot_id),
  CONSTRAINT final_review_target_package_wv_source_ck
    CHECK (workflow_version_source IN ('script_provenance', 'round_policy_snapshot'))
);

-- Database-enforced immutability: this is append-only approval provenance. Reject BOTH update and
-- delete at the DB boundary (application checks alone are insufficient — mirrors 023 sdam_binding).
CREATE OR REPLACE FUNCTION final_review_target_package_immutable() RETURNS trigger AS $$
  BEGIN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'final_review_target_package is immutable approval provenance — no DELETE permitted';
    END IF;
    RAISE EXCEPTION 'final_review_target_package is immutable approval provenance — no UPDATE permitted';
  END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_final_review_target_package_immutable ON final_review_target_package;
CREATE TRIGGER trg_final_review_target_package_immutable
  BEFORE UPDATE OR DELETE ON final_review_target_package
  FOR EACH ROW EXECUTE FUNCTION final_review_target_package_immutable();

-- #425 finding 4 — database-boundary stage guard: this evidence is FINAL-REVIEW ONLY. Reject a direct
-- insert whose referenced gate is not a `final_review` gate. The stage is read from PERSISTED canonical
-- gate data (never inferred from caller input); the trigger creates no snapshot and mutates no gate
-- state. Smallest PostgreSQL-native enforcement so an application bug cannot record cross-stage evidence.
CREATE OR REPLACE FUNCTION final_review_target_package_final_only() RETURNS trigger AS $$
  DECLARE gate_stage text;
  BEGIN
    SELECT stage INTO gate_stage FROM gate WHERE gate_id = NEW.gate_id;
    IF gate_stage IS DISTINCT FROM 'final_review' THEN
      RAISE EXCEPTION 'final_review_target_package accepts evidence only for a final_review gate '
                      '(gate % has stage %)', NEW.gate_id, coalesce(gate_stage, '<none>');
    END IF;
    RETURN NEW;
  END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_final_review_target_package_final_only ON final_review_target_package;
CREATE TRIGGER trg_final_review_target_package_final_only
  BEFORE INSERT ON final_review_target_package
  FOR EACH ROW EXECUTE FUNCTION final_review_target_package_final_only();

COMMIT;
