-- CR01 follow-up: turn content formats into an admin-managed content-type registry.
-- Idempotent. Same DDL is folded into db/init/schema.sql for fresh installs.

ALTER TABLE format
  ADD COLUMN IF NOT EXISTS format_key text,
  ADD COLUMN IF NOT EXISTS description text,
  ADD COLUMN IF NOT EXISTS production_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS platform_targets jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS uq_format_format_key
  ON format (format_key)
  WHERE format_key IS NOT NULL;

ALTER TABLE content_format
  ADD COLUMN IF NOT EXISTS lifecycle_status text NOT NULL DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS archived_at timestamptz,
  ADD COLUMN IF NOT EXISTS archived_by text;

UPDATE content_format
SET lifecycle_status = CASE WHEN active THEN 'active' ELSE 'archived' END
WHERE lifecycle_status NOT IN ('active', 'archived');
