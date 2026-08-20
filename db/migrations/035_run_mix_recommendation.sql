-- 035_run_mix_recommendation.sql
-- #377 — the canonical governed run-mix RECOMMENDATION authority, its durable proposal fence, and the
-- immutable per-run recommendation snapshot. Enabling prerequisite for #376 (which stays blocked).
--
-- WHAT THIS IS NOT. It is not an AI/model seam. #377's preflight established that no governed PLANNING
-- model route exists (every governed route is a content writer driven by workflow_stage.writer_mode;
-- provider selection lives in system_config/env topology and gates/provenance.py still declares
-- `used_model_provider` unsupported). Under GPT amendment 4 this authority is therefore DETERMINISTIC
-- and is labelled deterministic everywhere. The model-provenance columns exist so a later governed
-- route can record REQUESTED vs EFFECTIVE truthfully — they are 'not_applicable' today, never NULL-as-
-- unknown, and nothing here may be described as AI.
--
-- WHY NOT round_policy_snapshot. That table (024) is the pinned BASELINE-POLICY evidence: `format_mix`
-- means the accepted mix and `selected_version_ids` means the selected format versions. Recording the
-- initial recommendation, the operator's amendment, and the rationale there would redefine both fields
-- in the one artifact history reads. GPT amendment 11 rules for a SIBLING append-only table; 024 is
-- byte-untouched by this migration.
--
-- WHY WEIGHTS ARE KEYED BY content_format_version.version_id. A name can be renamed; a governed version
-- identity cannot. When the baseline eligible set moves to a version the active policy generation never
-- weighted, the authority FAILS CLOSED (typed blocked) instead of silently re-weighting — which is the
-- behaviour the "changed eligible set" red proof requires.
--
-- INITIALIZATION (CLAUDE.md guardrail + GPT amendment 3). There is NO baseline seed here and no
-- inferred default: weights are OPERATOR-OWNED and a missing current generation is a typed blocked
-- state, exactly as engine.ensure_baseline_policy hard-stops rather than seeding an inferred baseline.
-- Bootstrap/seed/reset paths may only ever CREATE a missing generation through the authorized domain
-- path; nothing here overwrites an operator-owned row.
--
-- IDEMPOTENT / INSPECT-FIRST (this repo has no migration ledger/runner): every object is guarded with
-- IF NOT EXISTS / CREATE OR REPLACE, so a re-run is a non-destructive no-op that preserves existing
-- rows and configuration. Additive only — no existing table, column, constraint or trigger is altered
-- or dropped. Wrapped in one transaction. Apply with psql; safe to apply more than once.
--
-- NO BACKFILL, deliberately. Runs planned before #377 had no recommendation, so they have no snapshot
-- and read as `unknown` — the same posture 033 takes for pre-#357 scripts. Inventing a historical
-- recommendation would fabricate provenance that never existed. V1's proposal-less POST /rounds keeps
-- working unchanged and records exactly that truthful `unknown`.

BEGIN;

-- ---------------------------------------------------------------------------------------------
-- (A) run_mix_recommendation_policy — the governed generations that authorize recommendation.
--
-- Same generation shape the repo already proves in 024: immutable identity, generation lineage,
-- exactly ONE 'current' per (scope, tenant, module) enforced by a partial unique index, and a
-- prospective change inserting a NEW generation rather than editing the active one in place.
CREATE TABLE IF NOT EXISTS run_mix_recommendation_policy (
  policy_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope             text NOT NULL DEFAULT 'default',
  generation        int  NOT NULL CHECK (generation >= 1),
  status            text NOT NULL DEFAULT 'current' CHECK (status IN ('current','superseded')),
  -- 'explicit' is the ONLY authorized source in this slice: the weights below are operator-declared.
  -- Deriving them (e.g. from methodology_hcs.recommended_formats) was explicitly NOT authorized, so it
  -- is not representable here rather than merely undocumented.
  weight_source     text NOT NULL DEFAULT 'explicit' CHECK (weight_source IN ('explicit')),
  -- {"<content_format_version.version_id>": <integer weight >= 0>} — relative weights, not counts.
  weights           jsonb NOT NULL,
  -- optional per-version floors/ceilings, same key space as `weights`; {} means unconstrained.
  min_counts        jsonb NOT NULL DEFAULT '{}'::jsonb,
  max_counts        jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- the apportionment rule this generation authorizes. 'largest_remainder_v1' IS planner.scale_
  -- distribution (Hamilton, input-order tie-break) — the deterministic function already in the repo.
  algorithm         text NOT NULL DEFAULT 'largest_remainder_v1'
                    CHECK (algorithm IN ('largest_remainder_v1')),
  -- the AUTHORITY/algorithm identity, distinct from the policy generation and from any commit SHA.
  authority_version text NOT NULL DEFAULT 'run_mix_authority_v1',
  notes             text,
  created_by        text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  superseded_at     timestamptz,
  superseded_by     uuid REFERENCES run_mix_recommendation_policy(policy_id),
  tenant_id         text NOT NULL DEFAULT 'default',
  module            text NOT NULL DEFAULT 'content',
  UNIQUE (scope, tenant_id, module, generation)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_mix_policy_one_current
  ON run_mix_recommendation_policy (scope, tenant_id, module) WHERE status = 'current';

-- Generation immutability, enforced by the DATABASE rather than by application discipline.
--
-- WHY THIS IS NOT OPTIONAL. A pinned snapshot cites a policy by (policy_id, generation). If the row
-- behind that citation could be edited in place, the same identity would describe different weights
-- before and after the edit, and every recommendation ever pinned to it would become ambiguous
-- retroactively — the exact failure the configuration-generation rule exists to prevent. "Only the
-- authorized path writes it" is a property of today's code, not of the data.
--
-- The ONLY permitted mutation is the governed one-way lineage transition: current -> superseded,
-- stamping superseded_at and superseded_by ONCE. Reactivation is refused, re-pointing a completed
-- lineage link is refused, and every identity/configuration column is frozen. Creation is unaffected
-- (INSERT does not fire this), so the authorized generation-minting path — supersede the prior row,
-- append the new current, then complete the lineage link — still works exactly as before.
CREATE OR REPLACE FUNCTION run_mix_recommendation_policy_freeze() RETURNS trigger AS $$
  BEGIN
    IF NEW.policy_id IS DISTINCT FROM OLD.policy_id
       OR NEW.scope IS DISTINCT FROM OLD.scope
       OR NEW.generation IS DISTINCT FROM OLD.generation
       OR NEW.weight_source IS DISTINCT FROM OLD.weight_source
       OR NEW.weights IS DISTINCT FROM OLD.weights
       OR NEW.min_counts IS DISTINCT FROM OLD.min_counts
       OR NEW.max_counts IS DISTINCT FROM OLD.max_counts
       OR NEW.algorithm IS DISTINCT FROM OLD.algorithm
       OR NEW.authority_version IS DISTINCT FROM OLD.authority_version
       OR NEW.notes IS DISTINCT FROM OLD.notes
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.module IS DISTINCT FROM OLD.module THEN
      RAISE EXCEPTION 'run_mix_recommendation_policy generation % is immutable — a change is a NEW '
                      'generation, never an in-place edit', OLD.generation;
    END IF;
    IF NEW.status <> 'superseded' THEN
      RAISE EXCEPTION 'run_mix_recommendation_policy may only transition current -> superseded '
                      '(a superseded generation is never reactivated)';
    END IF;
    -- Both lineage stamps are write-once: NULL -> value only.
    IF OLD.superseded_at IS NOT NULL AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at THEN
      RAISE EXCEPTION 'run_mix_recommendation_policy.superseded_at is write-once';
    END IF;
    IF OLD.superseded_by IS NOT NULL AND NEW.superseded_by IS DISTINCT FROM OLD.superseded_by THEN
      RAISE EXCEPTION 'run_mix_recommendation_policy.superseded_by is write-once';
    END IF;
    RETURN NEW;
  END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_run_mix_recommendation_policy_freeze ON run_mix_recommendation_policy;
CREATE TRIGGER trg_run_mix_recommendation_policy_freeze
  BEFORE UPDATE ON run_mix_recommendation_policy
  FOR EACH ROW EXECUTE FUNCTION run_mix_recommendation_policy_freeze();

-- ---------------------------------------------------------------------------------------------
-- (B) run_mix_proposal — the DURABLE server-side fence (GPT amendment 6, option A).
--
-- A proposal is NOT a run: it creates no slots, no gates, no history, and starting one is not accepted
-- operator activity. It carries an opaque id, is bound to the principal + scope that created it, has a
-- bounded expiry, and is CONSUMED EXACTLY ONCE inside the same transaction that creates the run.
--
-- The opaque id grants no authority by itself (amendment 8): every read/consume re-checks the bound
-- principal and scope, so a guessed or foreign id is a typed denial, not a disclosure.
CREATE TABLE IF NOT EXISTS run_mix_proposal (
  proposal_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  status               text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','consumed')),
  -- server-generated canonical digest over the whole proposal context (see gates/run_mix.py).
  digest_version       int  NOT NULL,
  digest               text NOT NULL,
  scope                text NOT NULL DEFAULT 'default',
  tenant_id            text NOT NULL DEFAULT 'default',
  module               text NOT NULL DEFAULT 'content',
  created_by           text NOT NULL,
  -- the prospective draft window: INCLUSIVE start/end, as the operator selects it.
  starts_on            date NOT NULL,
  ends_on              date NOT NULL,
  posts_per_day        int  NOT NULL CHECK (posts_per_day >= 1),
  expected_slots       int  NOT NULL CHECK (expected_slots >= 1),
  -- the ORDERED eligible set this recommendation was computed against (canonical order preserved).
  eligible_version_ids jsonb NOT NULL,
  recommended_mix      jsonb NOT NULL,   -- {"<framework name>": <count>} summing to expected_slots
  rationale            jsonb NOT NULL,   -- bounded STRUCTURED record; no free prose, no chain-of-thought
  authority_version    text NOT NULL,
  algorithm            text NOT NULL,
  policy_id            uuid NOT NULL REFERENCES run_mix_recommendation_policy(policy_id),
  policy_generation    int  NOT NULL,
  baseline_policy_id   uuid NOT NULL REFERENCES baseline_eligibility_policy(policy_id),
  baseline_generation  int  NOT NULL,
  methodology_version  text,
  workflow_version     text,
  -- REQUESTED vs EFFECTIVE model provenance, kept distinct so a later governed route cannot hide a
  -- substitution. 'not_applicable' today because this authority performs no model call at all.
  model_posture        text NOT NULL DEFAULT 'not_applicable'
                       CHECK (model_posture IN ('not_applicable','model_backed')),
  requested_route      text, requested_provider text, requested_model text,
  effective_route      text, effective_provider text, effective_model text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  expires_at           timestamptz NOT NULL,
  consumed_at          timestamptz,
  bound_round_id       text REFERENCES round(round_id),
  CHECK (ends_on >= starts_on),
  CHECK ((status = 'consumed') = (bound_round_id IS NOT NULL)),
  CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
);
-- One proposal binds AT MOST ONE run: the fence cannot be spread across two creations.
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_mix_proposal_round
  ON run_mix_proposal (bound_round_id) WHERE bound_round_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_run_mix_proposal_expiry
  ON run_mix_proposal (status, expires_at);
CREATE INDEX IF NOT EXISTS idx_run_mix_proposal_owner
  ON run_mix_proposal (created_by, tenant_id, module);

-- Frozen identity: the ONLY legal mutation is the single pending -> consumed transition that binds a
-- run. Every context column is immutable, a consumed proposal can never be re-opened or re-bound, and
-- no path can rewrite what was proposed after the operator saw it.
CREATE OR REPLACE FUNCTION run_mix_proposal_freeze() RETURNS trigger AS $$
  BEGIN
    IF NEW.proposal_id IS DISTINCT FROM OLD.proposal_id
       OR NEW.digest_version IS DISTINCT FROM OLD.digest_version
       OR NEW.digest IS DISTINCT FROM OLD.digest
       OR NEW.scope IS DISTINCT FROM OLD.scope
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.module IS DISTINCT FROM OLD.module
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.starts_on IS DISTINCT FROM OLD.starts_on
       OR NEW.ends_on IS DISTINCT FROM OLD.ends_on
       OR NEW.posts_per_day IS DISTINCT FROM OLD.posts_per_day
       OR NEW.expected_slots IS DISTINCT FROM OLD.expected_slots
       OR NEW.eligible_version_ids IS DISTINCT FROM OLD.eligible_version_ids
       OR NEW.recommended_mix IS DISTINCT FROM OLD.recommended_mix
       OR NEW.rationale IS DISTINCT FROM OLD.rationale
       OR NEW.authority_version IS DISTINCT FROM OLD.authority_version
       OR NEW.algorithm IS DISTINCT FROM OLD.algorithm
       OR NEW.policy_id IS DISTINCT FROM OLD.policy_id
       OR NEW.policy_generation IS DISTINCT FROM OLD.policy_generation
       OR NEW.baseline_policy_id IS DISTINCT FROM OLD.baseline_policy_id
       OR NEW.baseline_generation IS DISTINCT FROM OLD.baseline_generation
       OR NEW.methodology_version IS DISTINCT FROM OLD.methodology_version
       OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
       OR NEW.model_posture IS DISTINCT FROM OLD.model_posture
       OR NEW.requested_route IS DISTINCT FROM OLD.requested_route
       OR NEW.requested_provider IS DISTINCT FROM OLD.requested_provider
       OR NEW.requested_model IS DISTINCT FROM OLD.requested_model
       OR NEW.effective_route IS DISTINCT FROM OLD.effective_route
       OR NEW.effective_provider IS DISTINCT FROM OLD.effective_provider
       OR NEW.effective_model IS DISTINCT FROM OLD.effective_model
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
      RAISE EXCEPTION 'run_mix_proposal context is immutable — only the pending->consumed binding may change';
    END IF;
    IF OLD.status = 'consumed' THEN
      RAISE EXCEPTION 'run_mix_proposal % is already consumed — a fence is single-use', OLD.proposal_id;
    END IF;
    IF NEW.status <> 'consumed' THEN
      RAISE EXCEPTION 'run_mix_proposal may only transition pending -> consumed';
    END IF;
    RETURN NEW;
  END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_run_mix_proposal_freeze ON run_mix_proposal;
CREATE TRIGGER trg_run_mix_proposal_freeze
  BEFORE UPDATE ON run_mix_proposal
  FOR EACH ROW EXECUTE FUNCTION run_mix_proposal_freeze();

-- ---------------------------------------------------------------------------------------------
-- (C) run_mix_recommendation_snapshot — the IMMUTABLE per-run recommendation evidence.
--
-- Sibling to round_policy_snapshot, written in the SAME transaction as the run it describes. A
-- historical read resolves from HERE and never recomputes a past recommendation from current
-- configuration: activating a different policy/methodology generation afterwards cannot change a
-- single field of an already-written row.
CREATE TABLE IF NOT EXISTS run_mix_recommendation_snapshot (
  round_id             text PRIMARY KEY REFERENCES round(round_id) ON DELETE CASCADE,
  proposal_id          uuid NOT NULL UNIQUE REFERENCES run_mix_proposal(proposal_id),
  digest_version       int  NOT NULL,
  proposal_digest      text NOT NULL,
  authority_version    text NOT NULL,
  algorithm            text NOT NULL,
  policy_id            uuid NOT NULL REFERENCES run_mix_recommendation_policy(policy_id),
  policy_generation    int  NOT NULL,
  baseline_policy_id   uuid NOT NULL REFERENCES baseline_eligibility_policy(policy_id),
  baseline_generation  int  NOT NULL,
  methodology_version  text,
  workflow_version     text,
  starts_on            date NOT NULL,
  ends_on              date NOT NULL,
  posts_per_day        int  NOT NULL,
  expected_slots       int  NOT NULL,
  eligible_version_ids jsonb NOT NULL,
  recommended_mix      jsonb NOT NULL,   -- what the authority proposed
  submitted_mix        jsonb NOT NULL,   -- what the operator actually submitted (planner-validated)
  mix_amended          boolean NOT NULL, -- whether the two differ
  mix_delta            jsonb NOT NULL,   -- {"<framework>": submitted - recommended} for changed keys
  rationale            jsonb NOT NULL,
  model_posture        text NOT NULL,
  requested_route      text, requested_provider text, requested_model text,
  effective_route      text, effective_provider text, effective_model text,
  initiating_principal text NOT NULL,
  effective_principal  text NOT NULL,
  scope                text NOT NULL,
  tenant_id            text NOT NULL,
  module               text NOT NULL,
  -- canonical idempotency: same key + same request converges on this row; a different request with the
  -- same key is a typed conflict (the unique index makes a silent second binding impossible).
  idempotency_key      text,
  request_digest       text NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_mix_snapshot_idempotency
  ON run_mix_recommendation_snapshot (proposal_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Append-only, exactly like round_policy_snapshot: no path may replace, recompute or partially mutate
-- pinned recommendation evidence. DELETE is left to the round FK cascade only (whole-run removal).
CREATE OR REPLACE FUNCTION run_mix_recommendation_snapshot_no_update() RETURNS trigger AS $$
  BEGIN
    RAISE EXCEPTION 'run_mix_recommendation_snapshot is append-only evidence — no UPDATE permitted';
  END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_run_mix_recommendation_snapshot_no_update ON run_mix_recommendation_snapshot;
CREATE TRIGGER trg_run_mix_recommendation_snapshot_no_update
  BEFORE UPDATE ON run_mix_recommendation_snapshot
  FOR EACH ROW EXECUTE FUNCTION run_mix_recommendation_snapshot_no_update();

COMMIT;
