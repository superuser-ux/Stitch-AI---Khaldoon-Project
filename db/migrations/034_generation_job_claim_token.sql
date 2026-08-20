-- #362 — the ownership FENCE for durable Script execution.
--
-- WHY. #357 gave Scripts a durable job with a lease, but ownership was identified only by
-- `claimed_by` — a worker NAME, documented in 028 as "diagnostic: which worker holds the lease".
-- Two successive tenures by the same worker produce the SAME value, so a stale worker whose lease
-- had already been reclaimed could still satisfy an ownership check and persist output, provenance,
-- or a terminal transition over work another worker now owns. A timestamp cannot close that either:
-- it answers "when", not "which tenure".
--
-- `claim_token` is that missing tenure identity. A fresh UUID is minted on every claim AND every
-- reclaim, and every authoritative Script write is guarded by it, so the moment a job is reclaimed
-- the previous worker's token is dead and none of its writes can land.
--
-- This is the pattern already proven twice in this repo — `rework_operation` (031) and
-- `bulk_operation` (032) both fence exactly this way. Nothing novel is introduced here; the column
-- brings `generation_job` up to the ownership discipline its siblings already have.
--
-- SCOPE (GPT binding Amendment L, the single approved exception to correction K):
--   exactly one nullable column — NO backfill, NO default, NO index, NO uniqueness rule,
--   NO foreign key, NO check constraint, NO trigger, NO new table/lifecycle/principal/scheduler.
--
-- Inspect-first, transactional, idempotent, additive-only, safe to rerun. This repo has no migration
-- ledger/runner; apply once with psql. A rerun is a non-destructive no-op.
--
-- TOPIC IS UNTOUCHED. Topic paths never read or write this column. Neither unique index
-- (`uq_generation_job_round_token`, `uq_generation_job_script_manifest`) references an ownership
-- column, so Topic discovery, claim, arbitration, uniqueness, heartbeat and terminal behaviour are
-- unaffected by construction rather than by care.
--
-- EXISTING ROWS KEEP `claim_token IS NULL`, deliberately. A NULL token is not a wildcard: the fenced
-- predicates below require an exact match, so a row without a current token holds no newly fenced
-- Script authority and cannot be mistaken for an owned tenure. Backfilling would invent ownership
-- history that never existed.

BEGIN;

ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS claim_token uuid;

COMMIT;
