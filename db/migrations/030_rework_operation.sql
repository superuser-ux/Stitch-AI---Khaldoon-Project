-- 030 — Stage 2B-1 (#313 Codex P1-B) durable rework OPERATION state machine.
--
-- ADDITIVE ONLY. Every statement is IF NOT EXISTS; no rename/drop/rewrite/backfill; a rerun is a
-- non-destructive no-op.
--
-- WHY: a manual "rework from a version" is restore (append a revision) THEN regenerate (append another
-- revision + provenance) in a background writer. An idempotent restore row proved only that RESTORE
-- committed — not that the generation started or finished. A crash/restart, unavailable writer, or a
-- thread-start failure after restore left a durable restored revision with NO generated revision, and a
-- replay (same key) then returned idempotent and permanently SUPPRESSED the missing rework.
--
-- This table is the durable, recoverable OWNER of the whole restore+rework operation, keyed idempotently
-- per (slot_id, idempotency_key). Its `state` distinguishes queued -> running -> completed | failed, so a
-- replay/recovery RESUMES unfinished work and DEDUPLICATES only completed/in-flight duplicates. The
-- generated revision + provenance and the op's `completed` transition are written in ONE transaction
-- (via the writer's on-persist hook), so recovery re-drives only genuinely unfinished work — exactly one
-- generated revision/provenance results under crash-after-restore and concurrent replay.
CREATE TABLE IF NOT EXISTS rework_operation (
  op_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id           text NOT NULL REFERENCES slot(slot_id),
  idempotency_key   text NOT NULL,
  artifact          text NOT NULL DEFAULT 'topic',
  base_revision     int  NOT NULL,                 -- the revision this rework derives FROM
  restored_revision int,                           -- the restore's new head (NULL until restore runs)
  comment           text NOT NULL,                 -- the rework directive (the reviewer comment)
  actor             text NOT NULL DEFAULT 'system',
  state             text NOT NULL DEFAULT 'queued', -- queued | running | completed | failed
  generated_revision int,                          -- the rework's OUTPUT revision (set with completion)
  lease_expires_at  timestamptz,                   -- in-flight ownership lease (a stale lease is reclaimable)
  heartbeat_at      timestamptz,
  error_detail      text,
  tenant_id         text NOT NULL DEFAULT 'default',
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Idempotency identity: one operation per (slot_id, idempotency_key). A concurrent replay's INSERT loses
-- the race here (ON CONFLICT DO NOTHING) and resolves to the same op — never a second operation.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rework_operation_key ON rework_operation (slot_id, idempotency_key);
CREATE INDEX IF NOT EXISTS ix_rework_operation_recoverable ON rework_operation (state);
