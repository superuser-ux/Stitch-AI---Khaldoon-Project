-- ==========================================================================
-- Tanaghom — Phase 1 database schema (Postgres 16 + pgvector)
-- Place at: db/init/schema.sql  (auto-runs on first `docker compose up`)
-- Mirrors Phase1_Build_Spec_v1.md §2. Tune the vector dimension to your
-- embedding model (multilingual-e5-large = 1024).
-- ==========================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- for gen_random_uuid()

-- ---------- Enums ----------------------------------------------------------
CREATE TYPE slot_status AS ENUM
  ('EMPTY','RESERVED','SCHEDULE_APPROVED','TOPIC_PROPOSED','TOPIC_APPROVED','CHANGES_REQUESTED',  -- CHANGES_REQUESTED = awaiting rework
   'REJECTED',                                   -- reversible 'dropped' (recoverable via reopen)
   'DRAFT_ASSIGNED','APPROVED_ASSIGNED',
   'READY_FOR_PRODUCTION','PRODUCED','EDITED',   -- M9·B2 manual lifecycle stages
   'SCHEDULED','PUBLISHED','SKIPPED','REPLACED');
CREATE TYPE gate_scope     AS ENUM ('item','batch');
CREATE TYPE gate_policy    AS ENUM ('fixed','adhoc');
CREATE TYPE gate_status    AS ENUM ('open','approved','rejected','changes_requested','superseded');
CREATE TYPE decision_kind  AS ENUM ('approve','reject','request_change');
CREATE TYPE voice_status   AS ENUM ('seed','native_reviewed');
CREATE TYPE anchor_status  AS ENUM ('unverified','scholar_verified','not_applicable');

-- ---------- Methodology (seeded from CANON-010..014 + 42 records) ----------
CREATE TABLE pillar (
  pillar_code  text PRIMARY KEY,           -- P1_SELF ...
  code_short   text NOT NULL,              -- P1
  name_en      text NOT NULL,
  name_ar      text NOT NULL,
  scope        text
);

CREATE TABLE lens (
  lens_id           text PRIMARY KEY,       -- L1..L5
  name_ar           text NOT NULL,
  name_en           text NOT NULL,
  viewer_state      text,
  primary_action    text,
  default_hook_type text
);

CREATE TABLE hook_type (
  name      text PRIMARY KEY,               -- Painful Truth, The Collision, ...
  function  text
);

CREATE TABLE format (
  name             text PRIMARY KEY,        -- "Reel — Studio", ...
  format_key       text UNIQUE,
  description      text,
  use_case         text,
  lens_fit         jsonb,                   -- ["L2","L1"]
  production_notes text,
  production_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  platform_targets jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE hcs (
  hcs_id              text PRIMARY KEY,      -- "1.2"
  pillar_code         text NOT NULL REFERENCES pillar(pillar_code),
  seq_in_pillar       int  NOT NULL,         -- ordering for the cursor
  name_en             text NOT NULL,
  name_ar             text,
  core_wound          text,
  how_it_shows_up     text,
  false_belief        text,
  earthquake_sentence text,
  islamic_anchor      text,
  recommended_lenses  jsonb,                 -- ["L1","L2","L3"]
  recommended_formats jsonb,
  value_ladder        jsonb,
  voice_status        voice_status  NOT NULL DEFAULT 'seed',
  anchor_status       anchor_status NOT NULL DEFAULT 'unverified'
);

-- ---------- Planning + the no-repeat cursor --------------------------------
CREATE TABLE round (
  round_id            text PRIMARY KEY,      -- "R1"
  label               text,
  period_len_days     int  NOT NULL,
  posts_per_day       int  NOT NULL,
  post_times          jsonb NOT NULL,        -- ["09:00","20:00"]
  pillar_distribution jsonb NOT NULL,
  format_distribution jsonb NOT NULL,
  status              text NOT NULL DEFAULT 'planning',
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE hcs_cursor (                     -- one row per pillar
  pillar_code  text PRIMARY KEY REFERENCES pillar(pillar_code),
  last_hcs_id  text REFERENCES hcs(hcs_id),
  cycle_no     int  NOT NULL DEFAULT 1
);

CREATE TABLE lens_history (                   -- enforce lens != previous cycle
  hcs_id    text NOT NULL REFERENCES hcs(hcs_id),
  cycle_no  int  NOT NULL,
  lens      text NOT NULL REFERENCES lens(lens_id),
  PRIMARY KEY (hcs_id, cycle_no)
);

-- ---------- Slot = unit of work AND workflow state -------------------------
CREATE TABLE slot (
  slot_id      text PRIMARY KEY,             -- "R1-D01-AM"
  round_id     text NOT NULL REFERENCES round(round_id),
  day          int  NOT NULL,
  time_uae     text NOT NULL,
  pillar_code  text NOT NULL REFERENCES pillar(pillar_code),
  format       text REFERENCES format(name),
  hcs_id       text REFERENCES hcs(hcs_id),
  lens         text REFERENCES lens(lens_id),
  hook_type    text REFERENCES hook_type(name),
  cycle_no     int,                            -- HCS cycle this slot was assigned in (Planner)
  topic_angle  text,
  hook_text    text,
  script_ref   text,                           -- -> script.script_id (M3)
  status       slot_status NOT NULL DEFAULT 'EMPTY',
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_slot_round  ON slot(round_id);
CREATE INDEX idx_slot_status ON slot(status);

-- ---------- Topic ledger (dedup safety-net + coverage history) -------------
CREATE TABLE topic (
  topic_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id     text REFERENCES slot(slot_id),
  hcs_id      text NOT NULL REFERENCES hcs(hcs_id),
  lens        text REFERENCES lens(lens_id),
  round_id    text REFERENCES round(round_id), -- dedup scope (round / cycle)
  cycle_no    int,
  text_ar     text,
  text_en     text,
  rationale_ar text,                          -- reviewer-facing "why this topic now" (bilingual)
  rationale_en text,
  hook_text   text,                           -- the proposed spoken hook
  hook_type   text,
  revision    int NOT NULL DEFAULT 1,         -- co-creation: revision number
  feedback    text,                           -- reviewer note that drove THIS revision
  change_summary_ar text,                     -- v2's "how this addresses your comment" (bilingual)
  change_summary_en text,
  base_revision int,                          -- provenance: reworked/restored FROM this revision
  embedding   vector(1024),                  -- match your embedding model dim
  created_at  timestamptz NOT NULL DEFAULT now()
);
-- approximate-nearest-neighbour index for similarity dedup
CREATE INDEX idx_topic_embedding ON topic USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_topic_hcs ON topic(hcs_id);

-- ---------- Script ledger (Agent 2 output + mandatory-review flags) ---------
CREATE TABLE script (
  script_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id              text REFERENCES slot(slot_id),
  hcs_id               text NOT NULL REFERENCES hcs(hcs_id),
  lens                 text REFERENCES lens(lens_id),
  script_ar            text,
  structure            jsonb,
  final_line           text,
  delivery_notes       text,
  delivery_check       jsonb,                 -- CANON-012 self-assessment
  used_islamic_anchor  boolean NOT NULL DEFAULT false,
  needs_scholar_review boolean NOT NULL DEFAULT false,
  needs_native_review  boolean NOT NULL DEFAULT false,
  flags                jsonb,
  model                text,
  revision             int NOT NULL DEFAULT 1,   -- co-creation: revision number
  feedback             text,                     -- reviewer note that drove THIS revision
  change_summary_ar    text,                     -- v2's "how this addresses your comment" (bilingual)
  change_summary_en    text,
  base_revision        int,                      -- provenance: reworked/restored FROM this revision
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_script_slot ON script(slot_id);

-- ---------- Approval gates (item/batch, multi-approver, fixed/adhoc) -------
CREATE TABLE gate (
  gate_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope      gate_scope  NOT NULL,
  stage      text NOT NULL,                  -- 'topic_review' | 'script_review'
  policy     gate_policy NOT NULL DEFAULT 'fixed',
  rule_key   text NOT NULL DEFAULT 'any',    -- raw rule from config: any | all | N
  quorum     text NOT NULL DEFAULT 'any',    -- any | all | N
  status     gate_status NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gate_target (
  gate_id  uuid NOT NULL REFERENCES gate(gate_id) ON DELETE CASCADE,
  slot_id  text NOT NULL REFERENCES slot(slot_id),
  PRIMARY KEY (gate_id, slot_id)
);

CREATE TABLE gate_assignment (
  assignment_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  gate_id               uuid NOT NULL REFERENCES gate(gate_id) ON DELETE CASCADE,
  assignment_kind       text NOT NULL,        -- user | role | group
  assignment_key        text NOT NULL,        -- principal_id | role_id | group_id
  resolved_principal_id text,
  created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE approval_policy (
  policy_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stage       text NOT NULL,
  rule_key    text NOT NULL DEFAULT 'any',   -- any | all
  updated_by  text,
  tenant_id   text NOT NULL DEFAULT 'default',
  module      text NOT NULL DEFAULT 'content',
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (stage, tenant_id, module)
);

CREATE TABLE approval_policy_assignment (
  assignment_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id       uuid NOT NULL REFERENCES approval_policy(policy_id) ON DELETE CASCADE,
  assignment_kind text NOT NULL,             -- user | role | group
  assignment_key  text NOT NULL,             -- principal_id | role_id | group_id
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (policy_id, assignment_kind, assignment_key)
);

CREATE TABLE workflow (
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

CREATE TABLE workflow_version (
  version_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id    uuid NOT NULL REFERENCES workflow(workflow_id) ON DELETE CASCADE,
  version_no     int NOT NULL,
  status         text NOT NULL DEFAULT 'draft',      -- draft | active | inactive | archived
  source         text NOT NULL DEFAULT 'admin',      -- seed | admin
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

CREATE UNIQUE INDEX uq_workflow_version_one_active
  ON workflow_version (tenant_id, module)
  WHERE status = 'active';

CREATE TABLE workflow_stage (
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

CREATE TABLE workflow_transition (
  transition_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id         uuid NOT NULL REFERENCES workflow_version(version_id) ON DELETE CASCADE,
  from_stage_key     text NOT NULL,
  to_stage_key       text NOT NULL,
  condition_key      text NOT NULL DEFAULT 'approve',
  enabled            boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE methodology (
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

CREATE TABLE methodology_version (
  version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  methodology_id uuid NOT NULL REFERENCES methodology(methodology_id) ON DELETE CASCADE,
  version_no int NOT NULL,
  status text NOT NULL DEFAULT 'draft',
  source text NOT NULL DEFAULT 'seed',
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

CREATE UNIQUE INDEX uq_methodology_version_one_active
  ON methodology_version (tenant_id, module)
  WHERE status = 'active';

CREATE TABLE methodology_pillar (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  pillar_code text NOT NULL,
  code_short text NOT NULL,
  name_en text NOT NULL,
  name_ar text NOT NULL,
  scope text,
  PRIMARY KEY (version_id, pillar_code)
);

CREATE TABLE methodology_lens (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  lens_id text NOT NULL,
  name_ar text NOT NULL,
  name_en text NOT NULL,
  viewer_state text,
  primary_action text,
  default_hook_type text,
  PRIMARY KEY (version_id, lens_id)
);

CREATE TABLE methodology_hook_type (
  version_id uuid NOT NULL REFERENCES methodology_version(version_id) ON DELETE CASCADE,
  name text NOT NULL,
  function text,
  PRIMARY KEY (version_id, name)
);

CREATE TABLE methodology_hcs (
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

CREATE TABLE platform (
  platform_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform_key text NOT NULL,
  name text NOT NULL,
  channel_role text NOT NULL DEFAULT 'publish_target',
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

CREATE TABLE content_format (
  content_format_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  format_key text NOT NULL,
  name text NOT NULL,
  description text,
  active boolean NOT NULL DEFAULT true,
  lifecycle_status text NOT NULL DEFAULT 'active',
  archived_at timestamptz,
  archived_by text,
  created_by text,
  updated_by text,
  tenant_id text NOT NULL DEFAULT 'default',
  module text NOT NULL DEFAULT 'content',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (format_key, tenant_id, module)
);

CREATE TABLE content_format_version (
  version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  content_format_id uuid NOT NULL REFERENCES content_format(content_format_id) ON DELETE CASCADE,
  version_no int NOT NULL,
  status text NOT NULL DEFAULT 'active',
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

CREATE UNIQUE INDEX uq_content_format_version_one_active
  ON content_format_version (content_format_id)
  WHERE status = 'active';

CREATE TABLE gate_decision (
  gate_id     uuid NOT NULL REFERENCES gate(gate_id) ON DELETE CASCADE,
  slot_id     text REFERENCES slot(slot_id),  -- null = decision on whole batch
  approver_id text NOT NULL,
  decision    decision_kind NOT NULL,
  notes       text,
  revision    int,                            -- which artifact revision an approve targets (null = head)
  decided_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (gate_id, approver_id, slot_id)
);

-- ---------- Audit log (review everything) ----------------------------------
CREATE TABLE audit_log (
  id          bigserial PRIMARY KEY,
  entity      text NOT NULL,                 -- 'slot' | 'gate' | 'config' ...
  entity_id   text NOT NULL,
  action      text NOT NULL,                 -- 'status_change','approved',...
  actor       text,                          -- human or agent name
  detail      jsonb,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_log(entity, entity_id);

-- ---------- updated_at trigger for slot ------------------------------------
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_slot_touch BEFORE UPDATE ON slot
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ==========================================================================
-- M4.1 BLOCK 3 — cheap foundations (also in db/migrations/003_m4_foundations.sql)
-- ==========================================================================
-- Bilingual content (EN fillable later, no migration)
ALTER TABLE script ADD COLUMN IF NOT EXISTS script_en text;
ALTER TABLE topic  ADD COLUMN IF NOT EXISTS hook_en   text;

-- Minimal principal model — humans, system agents, per-user agent reps are ALL principals
DO $$ BEGIN
  CREATE TYPE principal_kind AS ENUM ('user','agent','agent_rep','system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE TABLE IF NOT EXISTS principal (
  principal_id    text PRIMARY KEY,
  kind            principal_kind NOT NULL,
  display_name_ar text, display_name_en text,
  role            text,
  owner_id        text REFERENCES principal(principal_id),
  tenant_id       text NOT NULL DEFAULT 'default',
  module          text NOT NULL DEFAULT 'platform',
  -- Unified Actor Model seams (adopt-now, safest defaults; behavior is M8+):
  autonomy_level  text  NOT NULL DEFAULT 'propose_only',  -- propose_only|recommend|act_with_approval|act_and_notify|autonomous
  capabilities    jsonb NOT NULL DEFAULT '[]'::jsonb,      -- tools/skills/models it CAN use
  permissions     jsonb NOT NULL DEFAULT '[]'::jsonb,      -- what it's ALLOWED to do (least privilege)
  scope           jsonb NOT NULL DEFAULT '{}'::jsonb,      -- tenant/module/workflow/stage
  active          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now()
);
INSERT INTO principal (principal_id, kind, display_name_ar, display_name_en, role, module) VALUES
  ('khal','user','خال','Khal','content_owner','content'),
  ('huda','user','هدى','Huda','reviewer','content'),
  ('system','system','النظام','System','system','platform'),
  ('agent.planner','agent','وكيل التخطيط','Planner agent','planner','content'),
  ('agent.topic','agent','وكيل المواضيع','Topic agent','writer','content'),
  ('agent.script','agent','وكيل النصوص','Script agent','writer','content'),
  ('writers','agent','وكلاء الكتابة','Writer agents','writer','content'),
  ('nour','user','نور','Nour','language_reviewer','content'),
  ('sheikh','user','الشيخ','Sheikh','scholar','content')
ON CONFLICT (principal_id) DO NOTHING;

-- CR01 foundations — normalized role/group membership for future approval assignment.
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

-- Attribution on the event log + tenant/module scoping on core tables (single tenant default)
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_kind text NOT NULL DEFAULT 'system';
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

-- M5 — reviewer disposition of a SUGGESTED review (escalate / waive-with-reason)
CREATE TABLE IF NOT EXISTS slot_review (
  slot_id     text NOT NULL REFERENCES slot(slot_id),
  review      text NOT NULL,
  disposition text NOT NULL,                 -- 'escalated' | 'waived'
  reason      text,
  actor       text,
  actor_kind  text NOT NULL DEFAULT 'user',
  tenant_id   text NOT NULL DEFAULT 'default',
  at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (slot_id, review)
);

-- ==========================================================================
-- M9 · Block B1 — Directive packages (the inter-stage handoff contract)
-- also in db/migrations/007_m9_directives.sql
-- ==========================================================================
CREATE TABLE IF NOT EXISTS directive (
  directive_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id        text NOT NULL REFERENCES slot(slot_id),
  schema_version text NOT NULL DEFAULT '1.0',
  type           text NOT NULL,                 -- strategy_directive | topic_directive | production_directive
  from_stage     text,                          -- stage that emitted it (null = origin)
  to_stage       text NOT NULL,                 -- stage that consumes it
  payload        jsonb NOT NULL,                -- the six-field package (intent bilingual)
  revision       int  NOT NULL DEFAULT 1,       -- ties to the topic/script revision it carries
  produced_by    text,                          -- principal that caused the handoff
  tenant_id      text NOT NULL DEFAULT 'default',
  module         text NOT NULL DEFAULT 'content',
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_directive_slot      ON directive(slot_id);
CREATE INDEX IF NOT EXISTS idx_directive_to_stage  ON directive(slot_id, to_stage);

-- ==========================================================================
-- M9 · Block B2 — minimal DAM (asset model) — also in 008_m9_manual_stages_dam.sql
-- ==========================================================================
CREATE TABLE IF NOT EXISTS asset (
  asset_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id          text NOT NULL REFERENCES slot(slot_id),
  stage            text NOT NULL,                 -- production | media_edit | distribution
  kind             text NOT NULL,                 -- raw_cut | edit | image | thumbnail | caption ...
  uri              text,                          -- path / URL / external ref (no binary in DB)
  storage          text NOT NULL DEFAULT 'reference', -- reference | local | s3 | drive ...
  version          int  NOT NULL DEFAULT 1,       -- version of THIS (slot,stage,kind,platform_variant)
  platform_variant text,                          -- null = master; instagram_reel | tiktok | youtube_short ...
  meta             jsonb NOT NULL DEFAULT '{}'::jsonb,
  status           text NOT NULL DEFAULT 'active',-- active | superseded | rejected
  created_by       text,
  tenant_id        text NOT NULL DEFAULT 'default',
  module           text NOT NULL DEFAULT 'content',
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_asset_slot       ON asset(slot_id);
CREATE INDEX IF NOT EXISTS idx_asset_slot_stage ON asset(slot_id, stage);

-- M9 version navigation — the approved-revision pointer (also in 010_m9_version_nav.sql)
CREATE TABLE IF NOT EXISTS slot_approval (
  slot_id    text NOT NULL REFERENCES slot(slot_id),
  artifact   text NOT NULL,                 -- topic | script
  revision   int  NOT NULL,
  approver   text,
  actor_kind text NOT NULL DEFAULT 'user',
  tenant_id  text NOT NULL DEFAULT 'default',
  at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (slot_id, artifact)
);

-- #439 — Stage 4 dedicated final-review SIGN-OFF receipt (also in db/migrations/037_final_review_signoff.sql).
-- One immutable, append-only record per governed sign-off of an immutable (gate_id, slot_id)
-- target-package; the receipt is the SOLE effect and grants no authority. This base definition (columns
-- + PK + the two UNIQUE constraints + the two CHECK constraints + the immutability trigger) is IDENTICAL
-- to migration 037. The cross-table FK to final_review_target_package is NOT inline here: this baseline
-- is applied before the migrations and does not yet define final_review_target_package (migration 036),
-- so migration 037 adds that FK via a guarded idempotent ALTER (mirrors 025's composite-FK convention).
CREATE TABLE IF NOT EXISTS final_review_signoff (
  signoff_id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  gate_id                        uuid NOT NULL,
  slot_id                        text NOT NULL,
  snapshot_id                    uuid NOT NULL,
  round_id                       text NOT NULL,
  topic_id                       uuid NOT NULL,
  topic_revision                 int  NOT NULL CHECK (topic_revision >= 1),
  script_id                      uuid NOT NULL,
  script_revision                int  NOT NULL CHECK (script_revision >= 1),
  workflow_version_id            uuid NOT NULL,
  workflow_version_source        text NOT NULL,
  production_directive_id        uuid,
  production_directive_revision  int,
  actor                          text NOT NULL,
  idempotency_key                text NOT NULL,
  request_digest                 text NOT NULL,
  outcome                        text NOT NULL CHECK (outcome = 'recorded'),
  recorded_at                    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT final_review_signoff_tuple_uq
    UNIQUE (gate_id, slot_id, snapshot_id, topic_revision, script_revision, workflow_version_id),
  CONSTRAINT final_review_signoff_idem_uq
    UNIQUE (gate_id, slot_id, idempotency_key),
  CONSTRAINT final_review_signoff_idem_len_ck
    CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 200),
  CONSTRAINT final_review_signoff_digest_len_ck
    CHECK (length(request_digest) = 64)
);
CREATE OR REPLACE FUNCTION final_review_signoff_immutable() RETURNS trigger AS $$
  BEGIN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'final_review_signoff is immutable sign-off provenance — no DELETE permitted';
    END IF;
    RAISE EXCEPTION 'final_review_signoff is immutable sign-off provenance — no UPDATE permitted';
  END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_final_review_signoff_immutable ON final_review_signoff;
CREATE TRIGGER trg_final_review_signoff_immutable
  BEFORE UPDATE OR DELETE ON final_review_signoff
  FOR EACH ROW EXECUTE FUNCTION final_review_signoff_immutable();
