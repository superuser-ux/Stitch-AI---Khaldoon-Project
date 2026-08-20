-- 031 — Stage 2B-1 (#313 Codex review #3 P1-1) rework operation OWNERSHIP fencing token.
--
-- ADDITIVE ONLY. IF NOT EXISTS; a rerun is a non-destructive no-op.
--
-- A claim mints a fresh `claim_token` = the exclusive ownership handle for THIS worker's tenure. The
-- worker's heartbeat renews the lease fenced by that token; completion and failure are fenced by it too.
-- So once a lease expires and the operation is re-claimed (a NEW token), the previous worker — even if
-- still alive and mid-generation — can no longer heartbeat, complete, or fail it: its writes match zero
-- rows and its generation transaction is rolled back. Exactly one owner acts at a time.
ALTER TABLE rework_operation ADD COLUMN IF NOT EXISTS claim_token uuid;
