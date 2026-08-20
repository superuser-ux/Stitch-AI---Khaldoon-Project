-- ==========================================================================
-- Gate hygiene — one open review per round+stage. A 'superseded' gate status lets
-- open_gate/stage_state auto-close ORPHAN open gates (targets already advanced) and
-- collapse accidental duplicates, instead of leaving stale open gates. Additive + idempotent.
-- ==========================================================================
ALTER TYPE gate_status ADD VALUE IF NOT EXISTS 'superseded';
