-- Migration 021 — #190 (#172 S1): authenticated-user → operating-principal binding foundation.
-- IAM proves identity; Tanaghom decides authority: an OIDC-authenticated user (issuer, subject)
-- maps to at most ONE operating principal here, and ONLY bound principals reach the gate API via
-- the existing signed-principal contract. Nothing in this table is an authorization input — the
-- authority plane (assignments, roles/groups, hard floors, policy_admin) is untouched.
-- email/display_name are provisioning HINTS for the future binding surface (S2), never authz data.
-- Additive only (explicitly authorized by #190).

CREATE TABLE IF NOT EXISTS user_identity (
  identity_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  issuer       text NOT NULL,
  subject      text NOT NULL,
  principal_id text NOT NULL REFERENCES principal(principal_id),
  email        text,
  display_name text,
  active       boolean NOT NULL DEFAULT true,
  created_by   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_by   text,
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (issuer, subject)
);

CREATE INDEX IF NOT EXISTS user_identity_principal_idx ON user_identity (principal_id);
