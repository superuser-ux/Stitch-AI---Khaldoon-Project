-- Migration 015 — CR01 DB-backed approval policy overrides
-- Admin-edited approval policies live in DB; YAML remains the default fallback.

CREATE TABLE IF NOT EXISTS approval_policy (
  policy_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stage       text NOT NULL,
  rule_key    text NOT NULL DEFAULT 'any',
  updated_by  text,
  tenant_id   text NOT NULL DEFAULT 'default',
  module      text NOT NULL DEFAULT 'content',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (stage, tenant_id, module)
);

CREATE TABLE IF NOT EXISTS approval_policy_assignment (
  assignment_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id       uuid NOT NULL REFERENCES approval_policy(policy_id) ON DELETE CASCADE,
  assignment_kind text NOT NULL,
  assignment_key  text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (policy_id, assignment_kind, assignment_key)
);
