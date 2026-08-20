-- ==========================================================================
-- Migration 005 — M5: reviewer disposition of a suggested review
-- Idempotent. The system SUGGESTS a review (flag); the reviewer disposes:
-- escalate it to the named reviewer, or waive it with an audited reason.
-- ==========================================================================
CREATE TABLE IF NOT EXISTS slot_review (
  slot_id     text NOT NULL REFERENCES slot(slot_id),
  review      text NOT NULL,                 -- 'native' | 'religious' (config reviews.<name>)
  disposition text NOT NULL,                 -- 'escalated' | 'waived'
  reason      text,                          -- required for a waiver
  actor       text,
  actor_kind  text NOT NULL DEFAULT 'user',
  tenant_id   text NOT NULL DEFAULT 'default',
  at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (slot_id, review)
);
