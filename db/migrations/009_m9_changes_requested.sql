-- ==========================================================================
-- M9 fix — close the co-creation loop: a distinct "awaiting rework" state +
-- a visible, comment-responsive rework response. Additive + idempotent.
--   request_change on resolve -> slot CHANGES_REQUESTED (NOT left at the review
--   status) -> excluded from any new gate + not approvable -> rework consumes
--   the saved comment (the rework directive) -> v2 -> back to the review status.
-- ==========================================================================

-- The dedicated "awaiting rework / regeneration" status.
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'CHANGES_REQUESTED';

-- v2's visible "how this addresses your comment" change-summary (bilingual), shown with history.
ALTER TABLE topic  ADD COLUMN IF NOT EXISTS change_summary_ar text;
ALTER TABLE topic  ADD COLUMN IF NOT EXISTS change_summary_en text;
ALTER TABLE script ADD COLUMN IF NOT EXISTS change_summary_ar text;
ALTER TABLE script ADD COLUMN IF NOT EXISTS change_summary_en text;
