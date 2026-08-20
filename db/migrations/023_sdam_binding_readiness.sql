-- 023_sdam_binding_readiness.sql
-- #244 — Production -> SDAM readiness adapter: provider-neutral identity binding + append-only
-- decision-evidence observations. TRANSACTIONAL ONE-SHOT (not an idempotent runner): apply once;
-- any pre-existing same-name object makes CREATE/ALTER/INSERT raise and rolls the whole migration
-- back with no partial mutation. (This repo has no migration ledger; a ledger/runner and a dedicated
-- non-superuser runtime role remain separate deferred infra/authority work.)
--
-- Ownership: SDAM/ResourceSpace stays authoritative for files/renditions/metadata/taxonomy/workflow/
-- permissions/history. Tanaghom persists ONLY (1) an opaque provider-neutral identity binding and
-- (2) minimum immutable decision-provenance evidence. ResourceSpace-specific external-ref shape
-- validation lives in the adapter, not here. Application-controlled observation writes are an
-- ephemeral-trial convention, NOT a DB-enforced authority boundary.

BEGIN;

-- (A) composite candidate key binding asset identity + human slot reference to one truth.
--     asset_id is already PK, so this UNIQUE is trivially valid (no data change); it is the native
--     composite-FK target for sdam_asset_binding.
ALTER TABLE asset ADD CONSTRAINT asset_id_version_slot_uniq UNIQUE (asset_id, version, slot_id);

-- (B) freshness/retry policy — Tanaghom governance, immutable + seeded.
CREATE TABLE sdam_freshness_policy (
  policy_version       int PRIMARY KEY CHECK (policy_version BETWEEN 1 AND 100000),
  ttl_seconds          int NOT NULL CHECK (ttl_seconds BETWEEN 1 AND 2592000),
  backoff_base_seconds int NOT NULL CHECK (backoff_base_seconds BETWEEN 1 AND 86400),
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION sdam_policy_immutable() RETURNS trigger AS $$
  BEGIN RAISE EXCEPTION 'sdam_freshness_policy is immutable'; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sdam_policy_immutable BEFORE UPDATE OR DELETE ON sdam_freshness_policy
  FOR EACH ROW EXECUTE FUNCTION sdam_policy_immutable();
INSERT INTO sdam_freshness_policy (policy_version, ttl_seconds, backoff_base_seconds) VALUES (1, 900, 30);

-- (C) sdam_asset_binding — immutable provider-neutral identity mapping.
CREATE TABLE sdam_asset_binding (
  binding_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id        uuid NOT NULL,
  asset_version   int  NOT NULL,
  slot_id         text NOT NULL,                                     -- human/content ref (navigation-only)
  provider_key    text NOT NULL CHECK (provider_key IN ('resourcespace')),
  external_ref    text NOT NULL CHECK (length(external_ref) BETWEEN 1 AND 128),  -- OPAQUE (shape validated in adapter)
  mapping_version int  NOT NULL CHECK (mapping_version BETWEEN 1 AND 1000),
  created_by      text NOT NULL CHECK (length(created_by) BETWEEN 1 AND 128),
  created_at      timestamptz NOT NULL,
  CONSTRAINT sdam_binding_asset_fk FOREIGN KEY (asset_id, asset_version, slot_id)
    REFERENCES asset (asset_id, version, slot_id) ON UPDATE NO ACTION ON DELETE NO ACTION,
  CONSTRAINT sdam_binding_assetver_provider_uniq UNIQUE (asset_id, asset_version, provider_key),
  CONSTRAINT sdam_binding_extref_uniq            UNIQUE (provider_key, external_ref)  -- cardinality invariant
);
CREATE INDEX idx_sdam_binding_slot  ON sdam_asset_binding(slot_id);
CREATE INDEX idx_sdam_binding_asset ON sdam_asset_binding(asset_id, asset_version);
CREATE FUNCTION sdam_binding_stamp() RETURNS trigger AS $$
  BEGIN NEW.created_at := now(); RETURN NEW; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sdam_binding_stamp BEFORE INSERT ON sdam_asset_binding
  FOR EACH ROW EXECUTE FUNCTION sdam_binding_stamp();
CREATE FUNCTION sdam_binding_immutable() RETURNS trigger AS $$
  BEGIN IF TG_OP='DELETE' THEN RAISE EXCEPTION 'sdam_asset_binding no delete'; END IF;
        RAISE EXCEPTION 'sdam_asset_binding no update'; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sdam_binding_immutable BEFORE UPDATE OR DELETE ON sdam_asset_binding
  FOR EACH ROW EXECUTE FUNCTION sdam_binding_immutable();

-- (D) sdam_readiness_observation — append-only decision evidence.
CREATE TABLE sdam_readiness_observation (
  observation_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id      uuid NOT NULL REFERENCES sdam_asset_binding(binding_id),   -- native NO ACTION
  observation_seq bigint NOT NULL,                                           -- DB-assigned monotonic per binding
  observation_key text NOT NULL CHECK (length(observation_key) BETWEEN 1 AND 200),
  result_code     text NOT NULL CHECK (result_code IN
     ('ready','not_ready_pending','not_ready_missing','not_ready_lineage_mismatch',
      'not_ready_taxonomy_mismatch','not_ready_ambiguous','unavailable','unauthorized','malformed')),  -- 'stale' derived-only
  digest_algorithm      text CHECK (digest_algorithm IS NULL OR digest_algorithm='sha256'),
  digest_schema_version int  CHECK (digest_schema_version IS NULL OR digest_schema_version BETWEEN 1 AND 1000),
  expected_digest text CHECK (expected_digest IS NULL OR expected_digest ~ '^[0-9a-f]{64}$'),
  observed_digest text CHECK (observed_digest IS NULL OR observed_digest ~ '^[0-9a-f]{64}$'),
  mismatch_code   text,
  evidence_source text NOT NULL CHECK (evidence_source='resourcespace'),      -- derived from binding provider (function)
  actor_type      text NOT NULL CHECK (actor_type IN ('system','operator')),
  actor_id        text NOT NULL CHECK (length(actor_id) BETWEEN 1 AND 128),
  policy_version  int  NOT NULL REFERENCES sdam_freshness_policy(policy_version),
  retry_class     text NOT NULL CHECK (retry_class IN
     ('retry_pending','retry_backoff','retry_reconcile','no_retry','refresh_ttl')),
  observed_at     timestamptz NOT NULL,                                       -- DB-forced (trigger)
  expires_at      timestamptz NOT NULL,                                       -- DB-derived from policy ttl (trigger)
  created_at      timestamptz NOT NULL,                                       -- DB-forced (trigger)
  CONSTRAINT sdam_obs_idem_uniq UNIQUE (binding_id, observation_key),
  CONSTRAINT sdam_obs_seq_uniq  UNIQUE (binding_id, observation_seq),
  CONSTRAINT sdam_obs_expiry CHECK (expires_at > observed_at),
  -- 9-result digest coherence (quartet present IFF digest-bearing; no orphans)
  CONSTRAINT sdam_obs_algo_coh   CHECK ((result_code IN ('ready','not_ready_lineage_mismatch','not_ready_taxonomy_mismatch')) = (digest_algorithm IS NOT NULL)),
  CONSTRAINT sdam_obs_schema_coh CHECK ((result_code IN ('ready','not_ready_lineage_mismatch','not_ready_taxonomy_mismatch')) = (digest_schema_version IS NOT NULL)),
  CONSTRAINT sdam_obs_exp_coh    CHECK ((result_code IN ('ready','not_ready_lineage_mismatch','not_ready_taxonomy_mismatch')) = (expected_digest IS NOT NULL)),
  CONSTRAINT sdam_obs_obs_coh    CHECK ((result_code IN ('ready','not_ready_lineage_mismatch','not_ready_taxonomy_mismatch')) = (observed_digest IS NOT NULL)),
  CONSTRAINT sdam_obs_ready_eq    CHECK (result_code <> 'ready' OR expected_digest = observed_digest),
  CONSTRAINT sdam_obs_mismatch_ne CHECK (result_code NOT IN ('not_ready_lineage_mismatch','not_ready_taxonomy_mismatch') OR expected_digest <> observed_digest),
  CONSTRAINT sdam_obs_mc_presence CHECK ((result_code IN ('not_ready_lineage_mismatch','not_ready_taxonomy_mismatch')) = (mismatch_code IS NOT NULL)),
  CONSTRAINT sdam_obs_mc_vocab CHECK (mismatch_code IS NULL
     OR (result_code='not_ready_lineage_mismatch'  AND mismatch_code IN ('lineage_slot','lineage_asset_version','lineage_script','lineage_approval','lineage_role'))
     OR (result_code='not_ready_taxonomy_mismatch' AND mismatch_code IN ('taxonomy_pillar','taxonomy_format','taxonomy_platform_variant','taxonomy_hcs','taxonomy_lens'))),
  CONSTRAINT sdam_obs_retry CHECK (
     (result_code='ready'             AND retry_class='refresh_ttl')     OR
     (result_code='not_ready_pending' AND retry_class='retry_pending')   OR
     (result_code='unavailable'       AND retry_class='retry_backoff')   OR
     (result_code='not_ready_missing' AND retry_class='retry_reconcile') OR
     (result_code IN ('unauthorized','malformed','not_ready_lineage_mismatch',
                      'not_ready_taxonomy_mismatch','not_ready_ambiguous') AND retry_class='no_retry'))
);
CREATE INDEX idx_sdam_obs_current ON sdam_readiness_observation(binding_id, observation_seq DESC);

-- DB-force times + derive expires_at from the recorded policy ttl (caller values ignored).
CREATE FUNCTION sdam_obs_stamp() RETURNS trigger AS $$
DECLARE v_ttl int; BEGIN
  SELECT ttl_seconds INTO v_ttl FROM sdam_freshness_policy WHERE policy_version=NEW.policy_version;
  IF v_ttl IS NULL THEN RAISE EXCEPTION 'unknown policy_version %', NEW.policy_version; END IF;
  NEW.observed_at := clock_timestamp(); NEW.created_at := now();
  NEW.expires_at  := NEW.observed_at + make_interval(secs => v_ttl); RETURN NEW; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sdam_obs_stamp BEFORE INSERT ON sdam_readiness_observation
  FOR EACH ROW EXECUTE FUNCTION sdam_obs_stamp();

-- Append-only + direct-insert guard. TRIAL CONVENTION, NOT a DB authority boundary (runtime role is
-- superuser today; real enforcement = dedicated non-superuser role, deferred).
CREATE FUNCTION sdam_obs_guard() RETURNS trigger AS $$
BEGIN IF TG_OP IN ('UPDATE','DELETE') THEN RAISE EXCEPTION 'sdam_readiness_observation append-only'; END IF;
  IF current_setting('sdam.append', true) IS DISTINCT FROM '1'
    THEN RAISE EXCEPTION 'use sdam_append_observation()'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_sdam_obs_guard BEFORE INSERT OR UPDATE OR DELETE ON sdam_readiness_observation
  FOR EACH ROW EXECUTE FUNCTION sdam_obs_guard();

-- (E) sole controlled write path: advisory-lock finalization only, revalidate binding, derive
-- evidence_source + observation_seq, converge same-key/same-payload, raise on different payload.
CREATE FUNCTION sdam_append_observation(
  p_binding_id uuid, p_observation_key text, p_result_code text,
  p_digest_algorithm text, p_digest_schema_version int, p_expected_digest text, p_observed_digest text,
  p_mismatch_code text, p_policy_version int, p_actor_type text, p_actor_id text, p_retry_class text
) RETURNS uuid AS $$
DECLARE v_provider text; v_seq bigint; v_e sdam_readiness_observation%ROWTYPE; v_id uuid;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('sdam_obs:'||p_binding_id::text));
  SELECT provider_key INTO v_provider FROM sdam_asset_binding WHERE binding_id=p_binding_id;
  IF v_provider IS NULL THEN RAISE EXCEPTION 'sdam_binding_absent' USING ERRCODE='23503'; END IF;
  SELECT * INTO v_e FROM sdam_readiness_observation WHERE binding_id=p_binding_id AND observation_key=p_observation_key;
  IF FOUND THEN
    IF (v_e.result_code,v_e.digest_algorithm,v_e.digest_schema_version,v_e.expected_digest,v_e.observed_digest,
        v_e.mismatch_code,v_e.evidence_source,v_e.actor_type,v_e.actor_id,v_e.policy_version,v_e.retry_class)
       IS NOT DISTINCT FROM
       (p_result_code,p_digest_algorithm,p_digest_schema_version,p_expected_digest,p_observed_digest,
        p_mismatch_code,v_provider,p_actor_type,p_actor_id,p_policy_version,p_retry_class)
    THEN RETURN v_e.observation_id;                                          -- converge (idempotent)
    ELSE RAISE EXCEPTION 'sdam_observation_conflict for key %', p_observation_key USING ERRCODE='23505'; END IF;
  END IF;
  SELECT COALESCE(MAX(observation_seq),0)+1 INTO v_seq FROM sdam_readiness_observation WHERE binding_id=p_binding_id;
  PERFORM set_config('sdam.append','1', true);
  INSERT INTO sdam_readiness_observation
    (binding_id,observation_seq,observation_key,result_code,digest_algorithm,digest_schema_version,expected_digest,
     observed_digest,mismatch_code,evidence_source,actor_type,actor_id,policy_version,retry_class,observed_at,expires_at,created_at)
  VALUES (p_binding_id,v_seq,p_observation_key,p_result_code,p_digest_algorithm,p_digest_schema_version,p_expected_digest,
     p_observed_digest,p_mismatch_code,v_provider,p_actor_type,p_actor_id,p_policy_version,p_retry_class,now(),now(),now())
  RETURNING observation_id INTO v_id;
  PERFORM set_config('sdam.append','', true);
  RETURN v_id;
END; $$ LANGUAGE plpgsql;

COMMIT;
