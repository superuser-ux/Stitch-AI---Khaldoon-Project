-- Migration 014 — CR01 gate assignment snapshots
-- Preserve the raw approval rule and configured assignments at gate-open time.

ALTER TABLE gate ADD COLUMN IF NOT EXISTS rule_key text NOT NULL DEFAULT 'any';

CREATE TABLE IF NOT EXISTS gate_assignment (
  assignment_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  gate_id               uuid NOT NULL REFERENCES gate(gate_id) ON DELETE CASCADE,
  assignment_kind       text NOT NULL,        -- user | role | group
  assignment_key        text NOT NULL,        -- principal_id | role_id | group_id
  resolved_principal_id text,
  created_at            timestamptz NOT NULL DEFAULT now()
);

