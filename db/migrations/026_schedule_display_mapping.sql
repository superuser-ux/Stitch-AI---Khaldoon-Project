-- 026_schedule_display_mapping.sql
-- #292 (Stage 1 of #294; consumes #279 residual 2, extends merged #271) —
-- governed schedule display-order / display-code mapping with optimistic concurrency.
--
-- ADDITIVE and NON-DESTRUCTIVE. Adds ONLY the persisted state needed for:
--   • an append-only, attributable MAPPING GENERATION per round (the combined schedule token), and
--   • the complete per-slot display position + human-facing code accepted by that generation.
--
-- CANONICAL IDENTITY IS UNTOUCHED. slot.slot_id remains the permanent, authoritative downstream key.
-- Nothing here derives, replaces, or rewrites it, and no descendant row (topic/script/asset) is
-- altered: descendants keep storing slot_id and resolve presentation THROUGH it.
--
-- PRESERVATION-FIRST — THIS MIGRATION BACKFILLS NOTHING. Existing rounds get no generation and are
-- therefore LEGACY BY ABSENCE: both V1 and V2 keep deriving their current presentation exactly as
-- today (dashboard/lib/content-id.ts). There is no bulk semantic reinterpretation of live rounds.
-- Initializing an existing round is a separately governed slice (#292 secondary ruling 1).
--
-- It seeds/resets/overwrites NO operator-owned policy or configuration.
--
-- Inspect-first, transactional, idempotent, and safe to rerun (every object guarded with
-- IF NOT EXISTS). This repo has no migration ledger/runner; apply once with psql. A rerun is a
-- non-destructive no-op.

BEGIN;

-- ---------------------------------------------------------------------------
-- An accepted mapping generation for a round. generation_no IS the round-scoped
-- COMBINED schedule token: it is bumped by BOTH a governed reorder AND a governed
-- schedule revision, so either operation invalidates a stale token held by the other
-- (no cross-operation conflict can be silently missed).
--
-- ATOMIC EXACTLY-ONE-WINNER: UNIQUE (round_id, generation_no) + the repo's established
-- `INSERT ... ON CONFLICT DO NOTHING RETURNING` idiom (#265/#267, engine.py:1484-1523).
-- The DB arbitrates; only the statement that actually inserted a row sees it in RETURNING,
-- so exactly one concurrent commit wins and only the winner writes its audit. There is no
-- application-level read-then-write.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schedule_display_generation (
  generation_id      bigserial PRIMARY KEY,
  round_id           text NOT NULL REFERENCES round(round_id) ON DELETE CASCADE,
  generation_no      int  NOT NULL,            -- the combined schedule token (1-based)
  base_generation_no int,                      -- the token the caller committed against (NULL for gen 1)
  origin             text NOT NULL,            -- 'reorder' | 'schedule_revision' | 'initial'
  actor              text NOT NULL,            -- attributable: who accepted this generation
  at                 timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT schedule_display_generation_round_no_key UNIQUE (round_id, generation_no),
  CONSTRAINT schedule_display_generation_origin_ck
    CHECK (origin IN ('reorder','schedule_revision','initial')),
  CONSTRAINT schedule_display_generation_no_ck CHECK (generation_no >= 1)
);

CREATE INDEX IF NOT EXISTS idx_sched_disp_gen_round
  ON schedule_display_generation(round_id, generation_no DESC);

-- ---------------------------------------------------------------------------
-- The COMPLETE accepted mapping for one generation: every slot of the round exactly once.
-- Immutable once its generation is committed — a new accepted ordering creates a NEW generation
-- rather than rewriting prior evidence, so historical events stay readable exactly as accepted.
--
-- display_code is the SERVER-AUTHORITATIVE human-facing code (V1/V2 prefer it whenever a
-- generation exists; legacy client derivation remains the fallback only for rounds with none).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schedule_display_position (
  generation_id    bigint NOT NULL REFERENCES schedule_display_generation(generation_id) ON DELETE CASCADE,
  slot_id          text   NOT NULL REFERENCES slot(slot_id) ON DELETE CASCADE,
  display_position int    NOT NULL,            -- 1-based presentation order within the round
  display_code     text   NOT NULL,            -- human-facing code as accepted by THIS generation
  PRIMARY KEY (generation_id, slot_id),
  -- uniqueness holds WITHIN a generation (codes are round-scoped, never global — see content-id.ts)
  CONSTRAINT schedule_display_position_pos_key  UNIQUE (generation_id, display_position),
  CONSTRAINT schedule_display_position_code_key UNIQUE (generation_id, display_code),
  CONSTRAINT schedule_display_position_pos_ck   CHECK (display_position >= 1)
);

CREATE INDEX IF NOT EXISTS idx_sched_disp_pos_slot
  ON schedule_display_position(slot_id);

COMMIT;
