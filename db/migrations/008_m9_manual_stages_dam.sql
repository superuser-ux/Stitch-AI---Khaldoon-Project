-- ==========================================================================
-- M9 · Block B2 — manual lifecycle stages + minimal DAM (asset model)
-- Additive + idempotent. Completes the content lifecycle past content-approval:
--   APPROVED_ASSIGNED -final_review-> READY_FOR_PRODUCTION -production_review->
--   PRODUCED -edit_review-> EDITED -distribution_review-> SCHEDULED -> PUBLISHED
-- The manual stages are plain `transition` gates (executor = human uploading
-- assets); no new engine control flow. AVP/POSTIZ drop into the generator slot.
-- ==========================================================================

-- New slot states for the manual stages (enum values; safe to add idempotently).
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'READY_FOR_PRODUCTION';
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'PRODUCED';
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'EDITED';

-- ---------- Minimal DAM — raw + edited media, versioned, per slot/stage -----
-- References media (uri), never stores binaries. Platform variants + versions.
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
