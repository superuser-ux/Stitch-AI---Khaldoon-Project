-- ==========================================================================
-- Migration 002 — M4.1 two-stage review (topics approved BEFORE scripting)
-- Idempotent. Same DDL folded into db/init/schema.sql for fresh installs.
-- Apply: psql ... -f db/migrations/002_m4_two_stage.sql   (NO surrounding BEGIN —
--        ALTER TYPE ... ADD VALUE must autocommit before the value is used.)
--   - slot_status gains TOPIC_PROPOSED, TOPIC_APPROVED (the topic gate's states)
--   - topic gains reviewer-facing bilingual rationale + revision/feedback (co-creation)
--   - script gains revision/feedback (co-creation history)
-- ==========================================================================

ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'TOPIC_PROPOSED' AFTER 'RESERVED';
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'TOPIC_APPROVED' AFTER 'TOPIC_PROPOSED';

-- Topic: reviewer-facing "why this topic now" (bilingual) + revision history
ALTER TABLE topic ADD COLUMN IF NOT EXISTS rationale_ar text;
ALTER TABLE topic ADD COLUMN IF NOT EXISTS rationale_en text;
ALTER TABLE topic ADD COLUMN IF NOT EXISTS hook_text   text;   -- the proposed spoken hook
ALTER TABLE topic ADD COLUMN IF NOT EXISTS hook_type   text;
ALTER TABLE topic ADD COLUMN IF NOT EXISTS revision    int NOT NULL DEFAULT 1;
ALTER TABLE topic ADD COLUMN IF NOT EXISTS feedback    text;   -- reviewer note that drove THIS revision

-- Script: revision history (regenerate-with-feedback)
ALTER TABLE script ADD COLUMN IF NOT EXISTS revision int NOT NULL DEFAULT 1;
ALTER TABLE script ADD COLUMN IF NOT EXISTS feedback text;
