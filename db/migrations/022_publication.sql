-- Migration 022 — #200 (pub.v1, #199): first-class publication persistence.
-- OPERATOR-AUTHORIZED migration (#199 authorization + the #200-recorded amendment authorizing
-- the bounded publication_raw_asset junction table). Publication is NOT a media asset version
-- (#198 correction): it has its own identities, idempotency domain, attempts, and history.
--
--   publication           — the governed INTENT to publish an exact approved source to an exact
--                           destination, plus (once attested/confirmed) the ≤1 durable OCCURRENCE.
--   publication_event     — append-only attempts/lifecycle events (DB-enforced immutability).
--   publication_raw_asset — the frozen raw SDAM readiness set, one row per referenced asset,
--                           protected by NATIVE non-cascading FKs (no trigger emulation).
--
-- Invariants enforced HERE (DB-level; application-only uniqueness is insufficient by contract):
--   * idempotency domain UNIQUE (provider_key, destination_account_scope, idempotency_key)
--   * provider-local refs scoped UNIQUE (provider, account scope, object type, external ref)
--   * ≤1 durable occurrence per intent (UNIQUE + set-once trigger)
--   * monotonic per-intent event_seq UNIQUE and DB-CHECKed >= 1 (nothing can be prepended under
--     the canonical first event); events immutable (no UPDATE/DELETE)
--   * identity/lineage/idempotency columns frozen after insert (guard trigger)
--   * occurrence evidence (url/refs/times/attestor) frozen once the occurrence is recorded —
--     future reconciliation/retraction appends typed events, it never overwrites
--   * ALL lineage FKs are native NO ACTION — publication truth can never be cascade-deleted or
--     retargeted, and raw readiness rows can never dangle (PostgreSQL's own FK machinery is the
--     MVCC-correct arbiter; the junction's freeze trigger only pins SET membership after create)
--   * intent creation is ATOMIC: a publication can only COMMIT together with its initial raw
--     readiness set and its CANONICAL first event — event_seq=1 AND event_type='intent_created'
--     (DEFERRABLE INITIALLY DEFERRED constraint trigger) — an eventless or wrongly-seeded parent
--     can never exist for a later transaction to append lineage to.

CREATE TABLE IF NOT EXISTS publication (
  publication_intent_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_occurrence_id uuid UNIQUE,              -- NULL until attested/confirmed; set once
  contract_version          text NOT NULL DEFAULT 'pub.v1' CHECK (contract_version = 'pub.v1'),
  execution_source          text NOT NULL CHECK (execution_source IN ('manual', 'provider')),

  -- provider / destination scoping (manual is a first-class source, not simulated provider data)
  provider_key              text NOT NULL,
  destination_account_scope text NOT NULL,            -- concrete account ref, or '-' = accountless
  platform_key              text NOT NULL,            -- normalized channel (platform registry vocabulary)
  destination               text,                     -- human-meaningful destination detail (bounded)
  external_object_type      text,
  external_ref              text,                     -- provider-local id, scoped by the composite below
  url                       text,                     -- permalink where available (never identity)

  -- operation idempotency (caller-supplied, reserved BEFORE the first mutation)
  idempotency_key           text NOT NULL,

  -- exact immutable source + approved-Edit lineage (stable ids; FKs NO ACTION)
  slot_id                   text NOT NULL REFERENCES slot(slot_id),
  script_id                 uuid REFERENCES script(script_id),
  edit_output_asset_id      uuid NOT NULL REFERENCES asset(asset_id),
  edit_output_version       int  NOT NULL,
  edit_output_rendition     text,
  distribution_gate_id      uuid NOT NULL REFERENCES gate(gate_id),
  production_gate_id        uuid REFERENCES gate(gate_id),
  edit_gate_id              uuid REFERENCES gate(gate_id),

  corrects_publication_intent_id uuid REFERENCES publication(publication_intent_id),

  -- actor + canonical times
  created_by                text NOT NULL,
  attested_by               text,
  provider_reported_at      timestamptz,
  occurred_at               timestamptz,
  recorded_at               timestamptz,
  created_at                timestamptz NOT NULL DEFAULT now(),

  UNIQUE (provider_key, destination_account_scope, idempotency_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS publication_external_ref_scope
  ON publication (provider_key, destination_account_scope, external_object_type, external_ref)
  WHERE external_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS publication_slot_idx ON publication (slot_id);

CREATE TABLE IF NOT EXISTS publication_event (
  event_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_intent_id uuid NOT NULL REFERENCES publication(publication_intent_id),
  -- history starts at the canonical seq 1 and only counts upward: a zero/negative sequence could
  -- be prepended UNDER the intent_created row and silently rewrite what "first" means
  event_seq             int  NOT NULL CONSTRAINT publication_event_seq_positive CHECK (event_seq >= 1),
  -- writable by this slice: intent_created / attempt_started / attempt_failed /
  -- published_manually_attested. The rest are RESERVED typed representation required by pub.v1
  -- (no commands/endpoints/UI in this slice).
  event_type            text NOT NULL CHECK (event_type IN (
                          'intent_created', 'attempt_started', 'attempt_failed',
                          'published_manually_attested',
                          'scheduled', 'attempt_cancelled', 'cancelled',
                          'published_externally_confirmed', 'reconciled', 'corrected_by',
                          'retracted')),
  event_source          text NOT NULL CHECK (event_source IN ('manual', 'provider', 'operator', 'system')),
  actor                 text NOT NULL,
  detail                jsonb NOT NULL DEFAULT '{}'::jsonb,  -- bounded supplementary evidence ONLY
  provider_reported_at  timestamptz,
  occurred_at           timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (publication_intent_id, event_seq)
);

-- Idempotent upgrade: dev DBs that created publication_event from the earlier unmerged shape
-- (no lower bound on event_seq) get the SAME named CHECK; no-op on fresh installs and re-runs.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'publication_event'::regclass
                   AND conname = 'publication_event_seq_positive') THEN
    ALTER TABLE publication_event
      ADD CONSTRAINT publication_event_seq_positive CHECK (event_seq >= 1);
  END IF;
END $$;

-- Append-only history: events can never be updated or deleted by application roles.
CREATE OR REPLACE FUNCTION publication_event_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'publication_event rows are append-only (pub.v1)';
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_publication_event_immutable ON publication_event;
CREATE TRIGGER trg_publication_event_immutable
  BEFORE UPDATE OR DELETE ON publication_event
  FOR EACH ROW EXECUTE FUNCTION publication_event_immutable();

-- Frozen publication identity/lineage/destination: only the occurrence/outcome columns may
-- transition, only from NULL (set-once), and ALL occurrence evidence freezes the moment the
-- occurrence is recorded. Deletion is prohibited. Future reconciliation/retraction appends
-- typed events — it never overwrites recorded truth.
CREATE OR REPLACE FUNCTION publication_frozen_fields() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'publication rows are never deleted (pub.v1)';
  END IF;
  IF NEW.publication_intent_id     IS DISTINCT FROM OLD.publication_intent_id
     OR NEW.contract_version       IS DISTINCT FROM OLD.contract_version
     OR NEW.execution_source       IS DISTINCT FROM OLD.execution_source
     OR NEW.provider_key           IS DISTINCT FROM OLD.provider_key
     OR NEW.destination_account_scope IS DISTINCT FROM OLD.destination_account_scope
     OR NEW.platform_key           IS DISTINCT FROM OLD.platform_key
     OR NEW.destination            IS DISTINCT FROM OLD.destination
     OR NEW.idempotency_key        IS DISTINCT FROM OLD.idempotency_key
     OR NEW.slot_id                IS DISTINCT FROM OLD.slot_id
     OR NEW.script_id              IS DISTINCT FROM OLD.script_id
     OR NEW.edit_output_asset_id   IS DISTINCT FROM OLD.edit_output_asset_id
     OR NEW.edit_output_version    IS DISTINCT FROM OLD.edit_output_version
     OR NEW.edit_output_rendition  IS DISTINCT FROM OLD.edit_output_rendition
     OR NEW.distribution_gate_id   IS DISTINCT FROM OLD.distribution_gate_id
     OR NEW.production_gate_id     IS DISTINCT FROM OLD.production_gate_id
     OR NEW.edit_gate_id           IS DISTINCT FROM OLD.edit_gate_id
     OR NEW.corrects_publication_intent_id IS DISTINCT FROM OLD.corrects_publication_intent_id
     OR NEW.created_by             IS DISTINCT FROM OLD.created_by
     OR NEW.created_at             IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'publication identity/lineage fields are immutable (pub.v1)';
  END IF;
  -- once the durable occurrence exists, EVERY occurrence-evidence column is frozen
  IF OLD.publication_occurrence_id IS NOT NULL AND (
        NEW.publication_occurrence_id IS DISTINCT FROM OLD.publication_occurrence_id
     OR NEW.attested_by          IS DISTINCT FROM OLD.attested_by
     OR NEW.occurred_at          IS DISTINCT FROM OLD.occurred_at
     OR NEW.recorded_at          IS DISTINCT FROM OLD.recorded_at
     OR NEW.url                  IS DISTINCT FROM OLD.url
     OR NEW.external_ref         IS DISTINCT FROM OLD.external_ref
     OR NEW.external_object_type IS DISTINCT FROM OLD.external_object_type
     OR NEW.provider_reported_at IS DISTINCT FROM OLD.provider_reported_at) THEN
    RAISE EXCEPTION 'publication occurrence evidence is frozen after recording (pub.v1)';
  END IF;
  -- and independent of the occurrence, these transition at most once (NULL -> value)
  IF (OLD.attested_by          IS NOT NULL AND NEW.attested_by          IS DISTINCT FROM OLD.attested_by)
     OR (OLD.occurred_at          IS NOT NULL AND NEW.occurred_at          IS DISTINCT FROM OLD.occurred_at)
     OR (OLD.recorded_at          IS NOT NULL AND NEW.recorded_at          IS DISTINCT FROM OLD.recorded_at)
     OR (OLD.provider_reported_at IS NOT NULL AND NEW.provider_reported_at IS DISTINCT FROM OLD.provider_reported_at) THEN
    RAISE EXCEPTION 'publication occurrence fields are set-once (pub.v1)';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_publication_frozen ON publication;
CREATE TRIGGER trg_publication_frozen
  BEFORE UPDATE OR DELETE ON publication
  FOR EACH ROW EXECUTE FUNCTION publication_frozen_fields();

-- raw SDAM lineage: normalized junction rows with NATIVE non-cascading FKs (operator-authorized
-- amendment recorded on #200). Both FKs are NO ACTION: an unknown asset can never be referenced,
-- and a referenced asset can never be deleted or id-retargeted from under committed publication
-- truth — PostgreSQL's own FK machinery is the arbiter, so the guarantee holds under MVCC
-- (parent rows are key-share locked by the FK check) with no trigger emulation.
CREATE TABLE IF NOT EXISTS publication_raw_asset (
  publication_intent_id uuid NOT NULL REFERENCES publication(publication_intent_id),
  asset_id              uuid NOT NULL REFERENCES asset(asset_id),
  PRIMARY KEY (publication_intent_id, asset_id)
);
CREATE INDEX IF NOT EXISTS publication_raw_asset_asset_idx ON publication_raw_asset (asset_id);

-- The raw readiness SET is frozen lineage: rows are written only while the intent is being
-- created (before its first event lands in the same transaction) and never change afterwards.
CREATE OR REPLACE FUNCTION publication_raw_asset_frozen() RETURNS trigger AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    RAISE EXCEPTION 'publication raw lineage is frozen (pub.v1)';
  END IF;
  IF EXISTS (SELECT 1 FROM publication_event e
             WHERE e.publication_intent_id = NEW.publication_intent_id) THEN
    RAISE EXCEPTION 'publication raw lineage is frozen after intent creation (pub.v1)';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_publication_raw_asset_frozen ON publication_raw_asset;
CREATE TRIGGER trg_publication_raw_asset_frozen
  BEFORE INSERT OR UPDATE OR DELETE ON publication_raw_asset
  FOR EACH ROW EXECUTE FUNCTION publication_raw_asset_frozen();

-- Atomic intent creation: the freeze trigger above pins the set AFTER history exists, but alone
-- it would let an EVENTLESS parent commit and collect lineage in a later transaction. This
-- deferred constraint trigger closes that hole at COMMIT of the creating transaction itself:
-- every newly inserted publication must already carry ≥1 raw readiness row and the CANONICAL
-- first event (event_seq=1, event_type='intent_created') — a history seeded any other way is
-- not intent creation.
-- (Deferred-to-commit, so the multi-statement create order inside the transaction stays free;
-- no xmin/txid heuristics involved.)
CREATE OR REPLACE FUNCTION publication_created_complete() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM publication_raw_asset r
                 WHERE r.publication_intent_id = NEW.publication_intent_id) THEN
    RAISE EXCEPTION 'publication % cannot commit without its raw readiness set (pub.v1)',
      NEW.publication_intent_id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM publication_event e
                 WHERE e.publication_intent_id = NEW.publication_intent_id
                   AND e.event_seq = 1 AND e.event_type = 'intent_created') THEN
    RAISE EXCEPTION 'publication % cannot commit without its canonical intent_created (seq 1) '
      'first event (pub.v1)', NEW.publication_intent_id;
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_publication_created_complete ON publication;
CREATE CONSTRAINT TRIGGER trg_publication_created_complete
  AFTER INSERT ON publication
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION publication_created_complete();

-- One-time in-place upgrade from the reviewed uuid[] + trigger-emulation shape (dev DBs that ran
-- the earlier revision of THIS unmerged migration): backfill the junction from the array, then
-- drop the emulation. No-op on fresh installs and on re-runs.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'publication' AND column_name = 'raw_asset_ids') THEN
    ALTER TABLE publication_raw_asset DISABLE TRIGGER trg_publication_raw_asset_frozen;
    INSERT INTO publication_raw_asset (publication_intent_id, asset_id)
      SELECT p.publication_intent_id, rid
      FROM publication p, unnest(p.raw_asset_ids) AS rid
      ON CONFLICT DO NOTHING;
    ALTER TABLE publication_raw_asset ENABLE TRIGGER trg_publication_raw_asset_frozen;
    DROP TRIGGER IF EXISTS trg_publication_raw_lineage ON publication;
    DROP TRIGGER IF EXISTS trg_asset_publication_lineage ON asset;
    DROP FUNCTION IF EXISTS publication_raw_lineage_exists();
    DROP FUNCTION IF EXISTS asset_publication_lineage_guard();
    DROP INDEX IF EXISTS publication_raw_asset_ids_gin;
    ALTER TABLE publication DROP COLUMN raw_asset_ids;
  END IF;
END $$;
