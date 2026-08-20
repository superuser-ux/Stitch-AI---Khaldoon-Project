-- Migration 013 — CR01 identity foundations
-- Add normalized role/group membership tables as groundwork for approval assignment.

CREATE TABLE IF NOT EXISTS principal_role (
  role_id          text PRIMARY KEY,
  display_name_ar  text,
  display_name_en  text,
  tenant_id        text NOT NULL DEFAULT 'default',
  module           text NOT NULL DEFAULT 'content',
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS principal_role_member (
  role_id          text NOT NULL REFERENCES principal_role(role_id) ON DELETE CASCADE,
  principal_id     text NOT NULL REFERENCES principal(principal_id) ON DELETE CASCADE,
  tenant_id        text NOT NULL DEFAULT 'default',
  module           text NOT NULL DEFAULT 'content',
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (role_id, principal_id)
);

CREATE TABLE IF NOT EXISTS principal_group (
  group_id         text PRIMARY KEY,
  display_name_ar  text,
  display_name_en  text,
  tenant_id        text NOT NULL DEFAULT 'default',
  module           text NOT NULL DEFAULT 'content',
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS principal_group_member (
  group_id         text NOT NULL REFERENCES principal_group(group_id) ON DELETE CASCADE,
  principal_id     text NOT NULL REFERENCES principal(principal_id) ON DELETE CASCADE,
  tenant_id        text NOT NULL DEFAULT 'default',
  module           text NOT NULL DEFAULT 'content',
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, principal_id)
);

INSERT INTO principal_role (role_id, display_name_en, tenant_id, module)
SELECT DISTINCT role, initcap(replace(role, '_', ' ')), tenant_id, module
FROM principal
WHERE role IS NOT NULL AND role <> ''
ON CONFLICT (role_id) DO NOTHING;

INSERT INTO principal_role_member (role_id, principal_id, tenant_id, module)
SELECT role, principal_id, tenant_id, module
FROM principal
WHERE role IS NOT NULL AND role <> ''
ON CONFLICT (role_id, principal_id) DO NOTHING;

