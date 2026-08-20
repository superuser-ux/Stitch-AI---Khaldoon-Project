-- #439 — Stage 4 dedicated final-review SIGN-OFF receipt (one immutable record per governed sign-off).
--
-- ADDITIVE, NO BACKFILL. Persists exactly one append-only receipt for a completed final-review
-- sign-off of an immutable (gate_id, slot_id) target-package. The receipt is the SOLE effect of the
-- sign-off command; it grants no authority, advances no lifecycle, and mutates no existing gate,
-- decision, coverage, snapshot, or package row. Present authority is (re)evaluated server-side from
-- the existing frozen snapshot + persisted coverage at sign-off time — this table only RECORDS that a
-- verified principal signed off a target whose present state was authoritatively approved.
--
-- Consistent with the repo's additive/idempotent convention (mirrors 036): guarded with
-- IF NOT EXISTS, wrapped in one transaction, safe to re-run. Applied manually with psql.
--
-- Apply-order note (mirrors 025): the base table (columns + PK + the two UNIQUE constraints + the two
-- CHECK constraints + the immutability trigger) is defined IDENTICALLY here and in db/init/schema.sql.
-- The cross-table FK to final_review_target_package (migration 036) is added here via a GUARDED
-- idempotent ALTER — never inline — because db/init/schema.sql is a pre-036 baseline applied BEFORE the
-- migrations and does not yet define final_review_target_package. This is exactly the pattern
-- migration 025 uses for its composite FKs, so the constraint is applied for BOTH a fresh (schema.sql
-- created the table without the FK, then 036 created the package, then this ALTER adds it) and an
-- already-applied DB (the ALTER supplies the missing FK). Every guard is name+table scoped => rerun no-op.
--
-- Authority boundary: this evidence CONFERS NO AUTHORITY. The `actor` column is immutable textual
-- provenance copied from the verified proxy principal at sign-off — it is NOT a principal relation and
-- introduces no new identity/eligibility source. The package-provenance columns copy the immutable
-- #423 final_review_target_package identity VERBATIM (same SQL types + nullability) so the receipt
-- carries full lineage without re-deriving or altering package semantics.

BEGIN;

CREATE TABLE IF NOT EXISTS final_review_signoff (
  signoff_id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  gate_id                        uuid NOT NULL,
  slot_id                        text NOT NULL,
  -- the four PUBLIC binding fields the caller submitted, revalidated against the stored package
  snapshot_id                    uuid NOT NULL,
  -- full immutable package identity + provenance, copied VERBATIM from final_review_target_package
  -- (types/nullability mirror migration 036 exactly — round_id is text, not uuid; the optional
  -- production-direction columns are nullable and recorded only when present on the package)
  round_id                       text NOT NULL,
  topic_id                       uuid NOT NULL,
  topic_revision                 int  NOT NULL CHECK (topic_revision >= 1),
  script_id                      uuid NOT NULL,
  script_revision                int  NOT NULL CHECK (script_revision >= 1),
  workflow_version_id            uuid NOT NULL,
  workflow_version_source        text NOT NULL,
  production_directive_id        uuid,
  production_directive_revision  int,
  -- immutable provenance of the verified principal (NOT a principal relation) + the sign-off contract
  actor                          text NOT NULL,
  idempotency_key                text NOT NULL,
  request_digest                 text NOT NULL,
  outcome                        text NOT NULL CHECK (outcome = 'recorded'),
  recorded_at                    timestamptz NOT NULL DEFAULT now(),
  -- one-time sign-off uniqueness: the canonical package tuple may be signed off at most once
  CONSTRAINT final_review_signoff_tuple_uq
    UNIQUE (gate_id, slot_id, snapshot_id, topic_revision, script_revision, workflow_version_id),
  -- idempotency uniqueness: a given key signs off a given target at most once
  CONSTRAINT final_review_signoff_idem_uq
    UNIQUE (gate_id, slot_id, idempotency_key),
  -- the idempotency key is a non-empty, <=200-char token after trimming UTF-8 whitespace
  CONSTRAINT final_review_signoff_idem_len_ck
    CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 200),
  -- the request digest is a fixed-width lowercase SHA-256 hex string (digest format v1)
  CONSTRAINT final_review_signoff_digest_len_ck
    CHECK (length(request_digest) = 64)
);

-- Cross-table FK to the immutable #423 package, added via a guarded idempotent ALTER (see apply-order
-- note above). The (gate_id, slot_id) target must be a real immutable final-review package.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname='final_review_signoff_target_fk'
                   AND conrelid='final_review_signoff'::regclass) THEN
    ALTER TABLE final_review_signoff
      ADD CONSTRAINT final_review_signoff_target_fk
      FOREIGN KEY (gate_id, slot_id) REFERENCES final_review_target_package (gate_id, slot_id);
  END IF;
END $$;

-- Database-enforced immutability: this is append-only sign-off provenance. Reject BOTH update and
-- delete at the DB boundary (application checks alone are insufficient — mirrors 036 / 023 sdam_binding).
CREATE OR REPLACE FUNCTION final_review_signoff_immutable() RETURNS trigger AS $$
  BEGIN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'final_review_signoff is immutable sign-off provenance — no DELETE permitted';
    END IF;
    RAISE EXCEPTION 'final_review_signoff is immutable sign-off provenance — no UPDATE permitted';
  END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_final_review_signoff_immutable ON final_review_signoff;
CREATE TRIGGER trg_final_review_signoff_immutable
  BEFORE UPDATE OR DELETE ON final_review_signoff
  FOR EACH ROW EXECUTE FUNCTION final_review_signoff_immutable();

COMMIT;
