-- 024_baseline_eligibility_policy.sql
-- #276 (D1 from audit #256) — the smallest governed seam that selects the CURRENT baseline eligible
-- content-format policy INDEPENDENTLY of global content_format lifecycle, then pins an IMMUTABLE
-- resolved policy snapshot when a run is planned. Additive only: no content_format lifecycle change,
-- no Pic + Caption archival, no catalogue mutation.
--
-- IDEMPOTENT / INSPECT-FIRST (this repo has no migration ledger/runner): every object is guarded with
-- IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT DO NOTHING, so a re-run is a non-destructive no-op
-- and never overwrites operator-owned rows. Safe to apply more than once. Wrapped in one transaction.

BEGIN;

-- (A) baseline_eligibility_policy — versioned policy generations. Exactly ONE 'current' per scope;
--     a prospective governed change inserts a new generation and supersedes the prior current one.
--     eligible_version_ids references content_format_version.version_id values (the eligible set),
--     decoupled from content_format.active — a later lifecycle/version change never edits a policy row.
CREATE TABLE IF NOT EXISTS baseline_eligibility_policy (
  policy_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope                text NOT NULL DEFAULT 'default',   -- applicable scope for new-run resolution
  generation           int  NOT NULL CHECK (generation >= 1),
  status               text NOT NULL DEFAULT 'current' CHECK (status IN ('current','superseded')),
  eligible_version_ids jsonb NOT NULL,                    -- ["<content_format_version.version_id>", ...]
  created_by           text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  superseded_at        timestamptz,
  superseded_by        uuid REFERENCES baseline_eligibility_policy(policy_id),
  tenant_id            text NOT NULL DEFAULT 'default',
  module               text NOT NULL DEFAULT 'content',
  UNIQUE (scope, tenant_id, module, generation)
);
-- exactly one current generation per (scope, tenant, module): DB-enforced, so zero/ambiguous current
-- is impossible to create and new-run resolution can fail closed on a missing current.
CREATE UNIQUE INDEX IF NOT EXISTS uq_baseline_policy_one_current
  ON baseline_eligibility_policy (scope, tenant_id, module) WHERE status = 'current';

-- (B) round_policy_snapshot — the append-only IMMUTABLE planning evidence pinned per run at plan time.
--     Holds only authoritative values available at planning time. A round read resolves from here,
--     never from the latest baseline policy.
CREATE TABLE IF NOT EXISTS round_policy_snapshot (
  round_id             text PRIMARY KEY REFERENCES round(round_id) ON DELETE CASCADE,
  baseline_policy_id   uuid NOT NULL REFERENCES baseline_eligibility_policy(policy_id),
  baseline_generation  int  NOT NULL,
  selected_version_ids jsonb NOT NULL,   -- {"<format name>": "<content_format_version.version_id>"}
  format_mix           jsonb NOT NULL,   -- {"<format name>": <count>}
  methodology_version  text,             -- methodology_version.version_id active at plan time (or null)
  workflow_version     text,             -- workflow_version.version_id active at plan time (or null)
  created_at           timestamptz NOT NULL DEFAULT now()
);

-- Snapshot immutability: block UPDATE so no normal path can replace/recompute/partially mutate the
-- pinned policy identity, selected version IDs, or mix. DELETE is intentionally left to the round FK
-- cascade only (whole-round removal, e.g. dev run-derived clear) — never a field-level mutation.
CREATE OR REPLACE FUNCTION round_policy_snapshot_no_update() RETURNS trigger AS $$
  BEGIN
    RAISE EXCEPTION 'round_policy_snapshot is append-only planning evidence — no UPDATE permitted';
  END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_round_policy_snapshot_no_update ON round_policy_snapshot;
CREATE TRIGGER trg_round_policy_snapshot_no_update
  BEFORE UPDATE ON round_policy_snapshot
  FOR EACH ROW EXECUTE FUNCTION round_policy_snapshot_no_update();

COMMIT;
