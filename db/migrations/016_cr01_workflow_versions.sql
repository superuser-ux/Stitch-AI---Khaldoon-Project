-- Migration 016 — CR01 workflow/version/stage/transition backend
-- Adds a DB-backed workflow control plane while keeping the existing gate engine compatible.

CREATE TABLE IF NOT EXISTS workflow (
  workflow_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_key  text NOT NULL,
  name          text NOT NULL,
  description   text,
  created_by    text,
  tenant_id     text NOT NULL DEFAULT 'default',
  module        text NOT NULL DEFAULT 'content',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workflow_key, tenant_id, module)
);

CREATE TABLE IF NOT EXISTS workflow_version (
  version_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id    uuid NOT NULL REFERENCES workflow(workflow_id) ON DELETE CASCADE,
  version_no     int NOT NULL,
  status         text NOT NULL DEFAULT 'draft',
  source         text NOT NULL DEFAULT 'admin',
  notes          text,
  created_by     text,
  updated_by     text,
  activated_by   text,
  tenant_id      text NOT NULL DEFAULT 'default',
  module         text NOT NULL DEFAULT 'content',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  activated_at   timestamptz,
  UNIQUE (workflow_id, version_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_version_one_active
  ON workflow_version (tenant_id, module)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS workflow_stage (
  stage_id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id                  uuid NOT NULL REFERENCES workflow_version(version_id) ON DELETE CASCADE,
  stage_key                   text NOT NULL,
  stage_label                 text NOT NULL,
  stage_group                 text NOT NULL,
  ordinal                     int NOT NULL,
  enabled                     boolean NOT NULL DEFAULT true,
  bypassable                  boolean NOT NULL DEFAULT false,
  mandatory                   boolean NOT NULL DEFAULT true,
  gate_stage                  text NOT NULL,
  stage_kind                  text NOT NULL DEFAULT 'transition',
  generator_kind              text,
  scope                       text,
  policy                      text,
  review_statuses             jsonb NOT NULL DEFAULT '[]'::jsonb,
  approve_to                  text,
  changes_to                  text,
  reject_to                   text,
  rework_mode                 text,
  generates_from              text,
  writer_mode                 text,
  requires_flag               text,
  allow_partial_batch         boolean NOT NULL DEFAULT false,
  enforce_mandatory_reviews   boolean NOT NULL DEFAULT false,
  approval_rule               text NOT NULL DEFAULT 'any',
  created_at                  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (version_id, stage_key),
  UNIQUE (version_id, ordinal)
);

CREATE TABLE IF NOT EXISTS workflow_transition (
  transition_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id         uuid NOT NULL REFERENCES workflow_version(version_id) ON DELETE CASCADE,
  from_stage_key     text NOT NULL,
  to_stage_key       text NOT NULL,
  condition_key      text NOT NULL DEFAULT 'approve',
  enabled            boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now()
);
