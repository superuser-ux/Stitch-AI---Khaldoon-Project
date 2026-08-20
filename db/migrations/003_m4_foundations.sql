-- ==========================================================================
-- Migration 003 — M4.1 BLOCK 3: cheap foundations (avoid future retrofit)
-- Idempotent. Same DDL folded into db/init/schema.sql for fresh installs.
-- Apply: psql ... -f db/migrations/003_m4_foundations.sql
--   - bilingual content fields (EN can be filled later, no migration)
--   - minimal principal model (users + agents + agent reps as identities + roles)
--   - agent/user attribution on the event log (actor_kind)
--   - tenant_id + module scoping on core tables (default single tenant / content module)
-- ==========================================================================

-- 1) Bilingual content fields (script EN optional; topic already has text/rationale _ar/_en)
ALTER TABLE script ADD COLUMN IF NOT EXISTS script_en text;   -- optional EN localization (future)
ALTER TABLE topic  ADD COLUMN IF NOT EXISTS hook_en   text;   -- EN hook (future / non-Arabic stakeholders)

-- 2) Minimal principal model — humans, system agents, and per-user agent reps are ALL principals
DO $$ BEGIN
  CREATE TYPE principal_kind AS ENUM ('user','agent','agent_rep','system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS principal (
  principal_id    text PRIMARY KEY,                 -- 'khal','huda','agent.topic',...
  kind            principal_kind NOT NULL,
  display_name_ar text,
  display_name_en text,
  role            text,                             -- content_owner|reviewer|writer|planner|...
  owner_id        text REFERENCES principal(principal_id),  -- agent_rep -> the human it acts for
  tenant_id       text NOT NULL DEFAULT 'default',
  module          text NOT NULL DEFAULT 'platform',
  active          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- seed the principals we already reference (approvers + agents). Idempotent.
INSERT INTO principal (principal_id, kind, display_name_ar, display_name_en, role, module) VALUES
  ('khal',  'user',  'خال',            'Khal',            'content_owner', 'content'),
  ('huda',  'user',  'هدى',            'Huda',            'reviewer',      'content'),
  ('system','system','النظام',          'System',          'system',        'platform'),
  ('agent.planner','agent','وكيل التخطيط','Planner agent',  'planner',       'content'),
  ('agent.topic',  'agent','وكيل المواضيع','Topic agent',   'writer',        'content'),
  ('agent.script', 'agent','وكيل النصوص', 'Script agent',   'writer',        'content'),
  ('writers',      'agent','وكلاء الكتابة','Writer agents', 'writer',        'content')
ON CONFLICT (principal_id) DO NOTHING;

-- 3) Attribution on the event log: which KIND of principal acted (user|agent|system)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_kind text NOT NULL DEFAULT 'system';

-- 4) tenant_id + module scoping on core tables (default single tenant, content module)
ALTER TABLE round     ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'default';
ALTER TABLE round     ADD COLUMN IF NOT EXISTS module    text NOT NULL DEFAULT 'content';
ALTER TABLE slot      ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'default';
ALTER TABLE slot      ADD COLUMN IF NOT EXISTS module    text NOT NULL DEFAULT 'content';
ALTER TABLE topic     ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'default';
ALTER TABLE script    ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'default';
ALTER TABLE gate      ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'default';
ALTER TABLE gate      ADD COLUMN IF NOT EXISTS module    text NOT NULL DEFAULT 'content';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'default';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS module    text NOT NULL DEFAULT 'content';
