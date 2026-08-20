-- Migration 020 — #184 managed topic-repetition policy (operator-authorized additive change)
-- The ACTIVE repetition/dedup policy for topic generation is DB-managed (top-level policy
-- authority controlled, every change audited in audit_log; audit is history, THIS row is the
-- persistence). system_config's engine.dedup_safety_net remains only the bootstrap fallback for
-- tunables — the effective production default is strict no-repeat across all history (#183/#184).
-- repeat_modes holds explicitly allowed re-expression modes (e.g. {"cross_format": true});
-- unknown modes are rejected at the API layer, the jsonb keeps the model open for future modes
-- (cross_platform etc.) without further schema work.

CREATE TABLE IF NOT EXISTS repetition_policy (
  policy_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_key           text NOT NULL DEFAULT 'topic_generation',
  enabled              boolean NOT NULL DEFAULT true,
  scope                text NOT NULL DEFAULT 'all',    -- all | round | hcs | current_cycle
  similarity_threshold numeric,                        -- NULL -> config bootstrap fallback
  max_regenerations    integer,                        -- NULL -> config bootstrap fallback
  repeat_modes         jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_by           text,
  tenant_id            text NOT NULL DEFAULT 'default',
  module               text NOT NULL DEFAULT 'content',
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (policy_key, tenant_id, module)
);
