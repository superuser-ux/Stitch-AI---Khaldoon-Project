-- ==========================================================================
-- Migration 001 — M3 Writers
-- Idempotent. Brings an already-initialised DB up to the M3 schema (the same
-- DDL is also folded into db/init/schema.sql for fresh installs).
--   - slot.cycle_no            : persist the Planner's HCS cycle per slot
--   - topic.round_id/cycle_no  : dedup scope (round / cycle)
--   - script table             : Agent 2 output + mandatory-review flags
-- Apply: psql ... -f db/migrations/001_m3_writers.sql
-- ==========================================================================

ALTER TABLE slot  ADD COLUMN IF NOT EXISTS cycle_no int;

ALTER TABLE topic ADD COLUMN IF NOT EXISTS round_id text REFERENCES round(round_id);
ALTER TABLE topic ADD COLUMN IF NOT EXISTS cycle_no int;
CREATE INDEX IF NOT EXISTS idx_topic_hcs ON topic(hcs_id);

CREATE TABLE IF NOT EXISTS script (
  script_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id              text REFERENCES slot(slot_id),
  hcs_id               text NOT NULL REFERENCES hcs(hcs_id),
  lens                 text REFERENCES lens(lens_id),
  script_ar            text,
  structure            jsonb,
  final_line           text,
  delivery_notes       text,
  delivery_check       jsonb,
  used_islamic_anchor  boolean NOT NULL DEFAULT false,
  needs_scholar_review boolean NOT NULL DEFAULT false,
  needs_native_review  boolean NOT NULL DEFAULT false,
  flags                jsonb,
  model                text,
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_script_slot ON script(slot_id);
