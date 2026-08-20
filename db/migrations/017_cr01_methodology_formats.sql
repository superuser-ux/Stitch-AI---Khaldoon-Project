-- Migration 017 — CR01 methodology/content-format version foundation
-- Adds DB-backed versioning for methodology and content formats while keeping
-- the current runtime tables (`pillar`, `lens`, `hook_type`, `format`, `hcs`)
-- as the materialized active copy used by the planner and writers.

CREATE TABLE IF NOT EXISTS methodology (
  methodology_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  methodology_key text NOT NULL,
  name text NOT NULL,
  description text,
  created_by text,
  tenant_id text NOT NULL DEFAULT 'default',
  module text NOT NULL DEFAULT 'content',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (methodology_key, tenant_id, module)
);

CREATE TABLE IF NOT EXISTS methodology_version (
  version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  methodology_id uuid NOT NULL REFERENCES methodology(methodology_id) ON DELETE CASCADE,
  version_no int NOT NULL,
  status text NOT NULL DEFAULT 'draft',        -- draft | active | inactive | archived
  source text NOT NULL DEFAULT 'seed',         -- seed | admin | import
  notes text,
  source_digest text,
  source_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text,
  updated_by text,
  activated_by text,
  tenant_id text NOT NULL DEFAULT 'default',
  module text NOT NULL DEFAULT 'content',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  UNIQUE (methodology_id, version_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_methodology_version_one_active
  ON methodology_version (tenant_id, module)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS methodology_pillar (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  pillar_code text NOT NULL,
  code_short text NOT NULL,
  name_en text NOT NULL,
  name_ar text NOT NULL,
  scope text,
  PRIMARY KEY (version_id, pillar_code)
);

CREATE TABLE IF NOT EXISTS methodology_lens (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  lens_id text NOT NULL,
  name_ar text NOT NULL,
  name_en text NOT NULL,
  viewer_state text,
  primary_action text,
  default_hook_type text,
  PRIMARY KEY (version_id, lens_id)
);

CREATE TABLE IF NOT EXISTS methodology_hook_type (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  name text NOT NULL,
  function text,
  PRIMARY KEY (version_id, name)
);

CREATE TABLE IF NOT EXISTS methodology_hcs (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  hcs_id text NOT NULL,
  pillar_code text NOT NULL,
  seq_in_pillar int NOT NULL,
  name_en text NOT NULL,
  name_ar text,
  core_wound text,
  how_it_shows_up text,
  false_belief text,
  earthquake_sentence text,
  islamic_anchor text,
  recommended_lenses jsonb,
  recommended_formats jsonb,
  value_ladder jsonb,
  voice_status voice_status NOT NULL DEFAULT 'seed',
  anchor_status anchor_status NOT NULL DEFAULT 'unverified',
  PRIMARY KEY (version_id, hcs_id)
);

CREATE TABLE IF NOT EXISTS platform (
  platform_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform_key text NOT NULL,
  name text NOT NULL,
  channel_role text NOT NULL DEFAULT 'publish_target',   -- publish_target | control_channel | analytics
  description text,
  active boolean NOT NULL DEFAULT true,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text,
  updated_by text,
  tenant_id text NOT NULL DEFAULT 'default',
  module text NOT NULL DEFAULT 'content',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (platform_key, tenant_id, module)
);

CREATE TABLE IF NOT EXISTS content_format (
  content_format_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  format_key text NOT NULL,
  name text NOT NULL,
  description text,
  active boolean NOT NULL DEFAULT true,
  created_by text,
  updated_by text,
  tenant_id text NOT NULL DEFAULT 'default',
  module text NOT NULL DEFAULT 'content',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (format_key, tenant_id, module)
);

CREATE TABLE IF NOT EXISTS content_format_version (
  version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_format_id uuid NOT NULL REFERENCES content_format(content_format_id) ON DELETE CASCADE,
  version_no int NOT NULL,
  status text NOT NULL DEFAULT 'active',      -- draft | active | inactive | archived
  source text NOT NULL DEFAULT 'seed',
  use_case text,
  lens_fit jsonb NOT NULL DEFAULT '[]'::jsonb,
  production_notes text,
  production_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  platform_targets jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_digest text,
  created_by text,
  updated_by text,
  activated_by text,
  tenant_id text NOT NULL DEFAULT 'default',
  module text NOT NULL DEFAULT 'content',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  UNIQUE (content_format_id, version_no)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_content_format_version_one_active
  ON content_format_version (content_format_id)
  WHERE status = 'active';
