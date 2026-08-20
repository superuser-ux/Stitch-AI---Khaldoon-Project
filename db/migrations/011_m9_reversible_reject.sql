-- ==========================================================================
-- Reversible reject ("git for content") — nothing is ever destroyed. Additive + idempotent.
--   reject -> a REVERSIBLE 'REJECTED' (dropped) state: excluded from the active batch / review /
--   regeneration, but REVOCABLE (reopen / un-reject -> back to the review status). Distinct from
--   request_change (which iterates via regeneration). All transitions stay append-only events.
-- ==========================================================================
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'REJECTED';
