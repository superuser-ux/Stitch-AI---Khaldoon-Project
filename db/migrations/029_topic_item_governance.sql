-- 029 — Stage 2B-1 (#313) canonical per-item Topic governance: additive integrity guards.
--
-- ADDITIVE ONLY. No rename/drop/rewrite/backfill of any operator-owned or historical value; no data
-- migration. Every statement is guarded (IF NOT EXISTS) so a rerun is a non-destructive no-op, and none
-- of these changes alter an existing revision row — they only enforce, going forward, invariants the
-- append-only revision model already relies on by convention (#313 preflight boundary B2).
--
-- 1. One row per (slot_id, revision): the append-only revision chain lives IN the topic table as N rows
--    per slot keyed by `revision`. Nothing enforced this at the DB level, so two concurrent
--    reworks/edits could both read max(revision)+1 and insert duplicate revision numbers for one slot.
--    A UNIQUE index makes the "one immutable row per attempt" contract a hard invariant and is the
--    overlap-protection backstop: the loser of a race gets a unique_violation, never a silent double-write.
-- PRECONDITION (fail LOUD, not cryptic): the unique index below cannot be created if this operator DB
-- already holds duplicate (slot_id, revision) topic rows — the pre-#313 "one row per attempt" was a
-- convention, never DB-enforced. Detect first and RAISE a descriptive error (count of offenders) so an
-- operator resolves it deliberately, rather than hitting an opaque CREATE INDEX failure. Read-only —
-- mutates nothing, and a clean DB (the common case) passes straight through.
DO $$
DECLARE dup_count int;
BEGIN
  SELECT count(*) INTO dup_count FROM (
    SELECT slot_id, revision FROM topic GROUP BY slot_id, revision HAVING count(*) > 1
  ) d;
  IF dup_count > 0 THEN
    RAISE EXCEPTION '029 precondition failed: % duplicate (slot_id,revision) topic row group(s) exist; resolve them before the append-only uniqueness index can be applied (#313 B2)', dup_count;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_topic_slot_revision ON topic (slot_id, revision);

-- 2. Per-item mutation idempotency. A structured edit / rework carries a client idempotency key; a replay
--    (double-click, retry) must return the ORIGINAL resulting revision without minting a second revision,
--    decision, or audit event. The key is recorded on the revision it produced; a partial UNIQUE index
--    scopes idempotency per slot and ignores legacy/null-key rows (every pre-#313 revision).
ALTER TABLE topic ADD COLUMN IF NOT EXISTS idempotency_key text;
CREATE UNIQUE INDEX IF NOT EXISTS uq_topic_slot_idempotency
  ON topic (slot_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
