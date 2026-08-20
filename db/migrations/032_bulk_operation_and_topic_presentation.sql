-- 032 — Stage 2B-2 (#314) bulk Topic operation ledger + distinct Topic presentation-order generations.
--
-- ADDITIVE ONLY. Every statement is IF NOT EXISTS; no rename/drop/rewrite/backfill; a rerun is a
-- non-destructive no-op. This repo has no migration ledger/runner; apply once with psql. It seeds/
-- resets/overwrites NO operator-owned policy or configuration.
--
-- Two additive resources, explicitly authorized by the #324/#323 architecture-gate closeout and the
-- Codex GO reconciliation as the load-bearing #314 acceptance requirements (NOT optional infra):
--
--   1. bulk_operation + bulk_operation_item — the durable, recoverable lifecycle + PER-ITEM OUTCOME
--      ledger for the selected PER-ITEM-COMMIT model. A bulk disposition over N slots maps each item to
--      an EXISTING canonical command (`decide(approve|request_change|reject)`); the ledger is the
--      idempotency + recovery + truthful-partial-outcome unit. `decide` is idempotent (gate_decision
--      upsert) and head-STABLE (it never mints a topic revision), so a crashed/replayed batch re-drives
--      only unsettled items and NEVER duplicates a completed one or misreports an unattempted one.
--
--   2. topic_presentation_generation + topic_presentation_position — an append-only, per-round
--      PRESENTATION-ORDER resource for the Topic workbench, DISTINCT from #292's Schedule display order
--      (schedule_display_generation, 026) and mirroring its exactly-one-winner concurrency
--      (UNIQUE(round_id, generation_no) + `INSERT ... ON CONFLICT DO NOTHING RETURNING`). It changes
--      PRESENTATION ORDER ONLY — never slot placement, Schedule order, disposition, approval, taxonomy,
--      methodology/config generation, or Topic revision identity. Canonical slot.slot_id is untouched.
--
-- PRESERVATION-FIRST — BACKFILLS NOTHING. Existing rounds get no presentation generation and are LEGACY
-- BY ABSENCE (the Topic workbench keeps deriving its current order exactly as today). Initializing an
-- existing round is a separately governed action, never an implicit side effect.

BEGIN;

-- =====================================================================================================
-- 1. BULK OPERATION LEDGER (per-item-commit model)
-- =====================================================================================================

-- The durable OWNER of a whole bulk disposition. `state` distinguishes queued -> running ->
-- completed | failed; `claim_token` (mirroring rework_operation 031) fences exactly one owner so a
-- crash/replay recovery drives the batch under a fresh token and a stale prior driver's writes hit
-- zero rows. Idempotency identity is (round_id, idempotency_key): a concurrent replay's INSERT loses
-- the race (ON CONFLICT DO NOTHING) and resolves to the SAME batch — never a second operation.
CREATE TABLE IF NOT EXISTS bulk_operation (
  batch_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id         text NOT NULL REFERENCES round(round_id) ON DELETE CASCADE,
  gate_id          uuid NOT NULL REFERENCES gate(gate_id),   -- the topic-review gate this batch disposes
  action           text NOT NULL,                            -- bulk_approve | bulk_request_change | bulk_drop
  actor            text NOT NULL,
  idempotency_key  text NOT NULL,
  request_digest   text NOT NULL,                            -- canonical digest of the IMMUTABLE request (tenant,round,gate,action,actor,comment,ordered [slot_id,expected_revision]); a replay of the SAME key with a DIFFERENT request is a typed conflict, never a silent wrong-op dedupe
  comment          text,                                     -- shared request_change comment (required for that action)
  state            text NOT NULL DEFAULT 'queued',           -- queued | running | completed | failed
  claim_token      uuid,                                     -- exclusive ownership fence (a re-claim mints a new token)
  lease_expires_at timestamptz,
  heartbeat_at     timestamptz,
  error_detail     text,
  tenant_id        text NOT NULL DEFAULT 'default',
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bulk_operation_action_ck
    CHECK (action IN ('bulk_approve','bulk_request_change','bulk_drop')),
  CONSTRAINT bulk_operation_state_ck
    CHECK (state IN ('queued','running','completed','failed'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bulk_operation_key ON bulk_operation (round_id, idempotency_key);
CREATE INDEX IF NOT EXISTS ix_bulk_operation_recoverable ON bulk_operation (state);

-- The PER-ITEM OUTCOME ledger: one row per selected slot, keyed by the stable slot_id. `outcome` is NULL
-- until the item is settled; a settled item is TERMINAL and NEVER re-driven; recovery resumes only rows
-- with a NULL outcome (still pending). `not_attempted` is a real settled outcome recorded when the batch
-- stops before an item is driven. `expected_revision` is the per-item CAS (the topic head the caller
-- selected against); `pinned_topic_id` optionally asserts "act on exactly this revision artifact".
CREATE TABLE IF NOT EXISTS bulk_operation_item (
  batch_id          uuid NOT NULL REFERENCES bulk_operation(batch_id) ON DELETE CASCADE,
  slot_id           text NOT NULL REFERENCES slot(slot_id),
  seq               int  NOT NULL,                           -- deterministic drive order (ascending slot_id)
  expected_revision int  NOT NULL,                           -- per-item CAS: MANDATORY exact topic head the caller pinned (NO NULL=head — #314 exact-current-head discipline)
  outcome           text,                                    -- succeeded|denied|conflicted|stale|failed|not_attempted (NULL = pending)
  reason            text,                                    -- typed denial/conflict reason (verbatim)
  attempted_at      timestamptz,
  settled_at        timestamptz,
  PRIMARY KEY (batch_id, slot_id),
  CONSTRAINT bulk_operation_item_expected_revision_ck CHECK (expected_revision >= 1),
  CONSTRAINT bulk_operation_item_outcome_ck
    CHECK (outcome IS NULL
        OR outcome IN ('succeeded','denied','conflicted','stale','failed','not_attempted'))
);

-- Pending-item lookup for recovery + status projection.
CREATE INDEX IF NOT EXISTS ix_bulk_operation_item_pending
  ON bulk_operation_item (batch_id) WHERE outcome IS NULL;

-- =====================================================================================================
-- 2. TOPIC-WORKBENCH PRESENTATION-ORDER GENERATIONS  (DISTINCT from #292 Schedule order)
-- =====================================================================================================

-- An accepted PRESENTATION-ORDER generation for a round's Topic workbench. generation_no is the
-- presentation-order token (1-based) and is DISTINCT from #292's schedule_token: reordering the Topic
-- presentation never bumps the schedule token and vice-versa. ATOMIC EXACTLY-ONE-WINNER via
-- UNIQUE (round_id, generation_no) + the repo's `INSERT ... ON CONFLICT DO NOTHING RETURNING` idiom;
-- the DB arbitrates, only the inserting statement sees RETURNING, so exactly one concurrent commit wins.
CREATE TABLE IF NOT EXISTS topic_presentation_generation (
  generation_id      bigserial PRIMARY KEY,
  round_id           text NOT NULL REFERENCES round(round_id) ON DELETE CASCADE,
  generation_no      int  NOT NULL,            -- presentation-order token (1-based), DISTINCT from schedule_token
  base_generation_no int,                      -- the token the caller committed against (NULL for gen 1)
  origin             text NOT NULL,            -- 'reorder' | 'initial'
  actor              text NOT NULL,            -- attributable: who accepted this generation
  at                 timestamptz NOT NULL DEFAULT now(),
  tenant_id          text NOT NULL DEFAULT 'default',
  CONSTRAINT topic_presentation_generation_round_no_key UNIQUE (round_id, generation_no),
  CONSTRAINT topic_presentation_generation_origin_ck CHECK (origin IN ('reorder','initial')),
  CONSTRAINT topic_presentation_generation_no_ck CHECK (generation_no >= 1)
);

CREATE INDEX IF NOT EXISTS idx_topic_pres_gen_round
  ON topic_presentation_generation(round_id, generation_no DESC);

-- The COMPLETE accepted presentation order for one generation: every included slot exactly once.
-- Immutable once its generation is committed — a new accepted order creates a NEW generation rather than
-- rewriting prior evidence. PRESENTATION ONLY: there is deliberately NO display_code here (human-facing
-- codes remain #292 Schedule's domain); this resource carries position, nothing else.
CREATE TABLE IF NOT EXISTS topic_presentation_position (
  generation_id    bigint NOT NULL REFERENCES topic_presentation_generation(generation_id) ON DELETE CASCADE,
  slot_id          text   NOT NULL REFERENCES slot(slot_id) ON DELETE CASCADE,
  display_position int    NOT NULL,            -- 1-based presentation order within the round
  PRIMARY KEY (generation_id, slot_id),
  CONSTRAINT topic_presentation_position_pos_key UNIQUE (generation_id, display_position),
  CONSTRAINT topic_presentation_position_pos_ck  CHECK (display_position >= 1)
);

CREATE INDEX IF NOT EXISTS idx_topic_pres_pos_slot
  ON topic_presentation_position(slot_id);

COMMIT;
