-- #357 Stage 3A — governed Script generation attempt identity + provenance.
--
-- WHY THIS EXISTS. Before #357 Script generation ran on `gates/jobs.py`: an IN-PROCESS dict guarded by
-- a threading lock, capped at 50 entries with eviction. That registry cannot express a durable attempt
-- identity, cannot enforce at-most-one active attempt, and loses every record on restart — after which
-- `stage_state` (which consults it) truthfully-looking-ly re-offers "generate" while work may still be
-- in flight. Scripts therefore move onto the SAME durable `generation_job` mechanism Topics already use.
-- This REMOVES the second mechanism; it does not add one.
--
-- Inspect-first, transactional, idempotent, additive-only, safe to rerun. This repo has no migration
-- ledger/runner; apply once with psql. A rerun is a non-destructive no-op.
--
-- TOPIC ARBITRATION IS UNTOUCHED. Every statement below either adds a new object or relaxes a
-- constraint in a way Topic rows cannot observe. The existing Topic uniqueness index is not dropped,
-- rebuilt, broadened or reinterpreted. See the DROP NOT NULL note for the one relaxation and why it is
-- provably invisible to Topic arbitration.

BEGIN;

-- ---------------------------------------------------------------------------------------------
-- 1. Script rows must not be forced to carry a Schedule token.
--
-- `accepted_schedule_token` is the Topic identity component: Topics derive from an accepted Schedule,
-- so pinning it is correct THERE. Scripts derive from approved TOPIC revisions; a Script row carrying
-- a Schedule token merely to satisfy a NOT NULL would be a false pin, and two genuinely different
-- Script manifests sharing one Schedule token would collapse under the Topic index.
--
-- WHY THIS CANNOT CHANGE TOPIC ARBITRATION: Topic rows are minted at Schedule acceptance and ALWAYS
-- supply a token, so no existing or future Topic row can hold NULL here. The Topic unique index
-- (round_id, accepted_schedule_token, stage) therefore sees exactly the same values, in the same
-- shape, arbitrating identically. Relaxing a NOT NULL removes no uniqueness and rejects nothing that
-- was previously accepted.
ALTER TABLE generation_job ALTER COLUMN accepted_schedule_token DROP NOT NULL;

-- ---------------------------------------------------------------------------------------------
-- 2. The governed Script attempt: an immutable manifest + its versioned digest.
--
-- The manifest is an EXECUTABLE INPUT CONTRACT, not descriptive metadata. Governed execution consumes
-- its pinned tuples and configuration directly and never reselects slots or re-resolves live config —
-- otherwise an attempt authorized against one input set could execute against another after a
-- configuration change, which is exactly the silent reinterpretation this directive forbids.
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS manifest            jsonb;
-- Versioned digest of the canonical ordered manifest. Versioned because canonicalization itself is a
-- contract: field names, null/not-applicable representation, tuple ordering, string encoding, snapshot
-- hashing and the digest algorithm can only change under a new version, never silently.
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS manifest_digest     text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS manifest_version    text;

-- The accepted topic_review decision that governs EVERY revision in the manifest, plus its frozen
-- affirmative authority. Authorization compares the effective signed principal against THIS snapshot,
-- never against current assignments, roles, or client-supplied claims.
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS source_gate_id      uuid;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS source_gate_generation text;

-- Provenance, explicitly NOT identity (a different actor or correlation id does not mint a new
-- attempt; it is recorded against the same one).
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS initiating_actor    text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS effective_actor     text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS correlation_id      text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS idempotency_key     text;

-- REQUESTED route/provider/model — caller-selectable and therefore part of identity (changing them is
-- regeneration, out of scope here). The EFFECTIVE values live on script_provenance so a fallback or
-- substitution is visible as a difference rather than hidden by overwriting one field.
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS requested_route     text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS requested_provider  text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS requested_model     text;

-- ---------------------------------------------------------------------------------------------
-- 3. Script uniqueness — SCRIPT-SCOPED, leaving the Topic index alone.
--
-- A PARTIAL unique index: it constrains only rows with stage='script', so it is invisible to Topic
-- arbitration by construction rather than by care. Scoped by round_id as well as the digest, because
-- the digest is canonical-but-not-globally-namespaced.
--
-- This is the at-most-one-active-attempt guarantee: a replay of the same governed manifest cannot
-- insert a second job, so a duplicate request observes the existing attempt instead of racing it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_job_script_manifest
  ON generation_job (round_id, manifest_digest)
  WHERE stage = 'script';

-- ---------------------------------------------------------------------------------------------
-- 4. Per-result Script provenance.
--
-- Mirrors topic_provenance's proven shape MINUS the Topic-only novelty/order/concept-family fields
-- (Scripts must not inherit concerns that are not theirs), PLUS the requested/effective split.
--
-- Stub-mode and genuinely inapplicable values are recorded as the literal 'not_applicable' or left
-- absent with a reason — never guessed, never inherited from a later run.
CREATE TABLE IF NOT EXISTS script_provenance (
  provenance_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  script_id       uuid NOT NULL REFERENCES script(script_id),
  revision        int  NOT NULL DEFAULT 1,
  job_id          uuid REFERENCES generation_job(job_id),
  slot_id         text REFERENCES slot(slot_id),

  -- the exact consumed input, pinned. Before #357 this was resolved at execution and DISCARDED.
  topic_id            uuid,
  topic_revision      int,

  -- the configuration generation actually consumed
  workflow_version_id     uuid,
  methodology_version     text,
  framework_version       text,
  content_format_version  text,
  writer_contract_version text,
  prompt_template_version text,

  -- REQUESTED vs EFFECTIVE, kept distinct so substitution or fallback cannot hide
  requested_route     text,
  requested_provider  text,
  requested_model     text,
  effective_route     text,
  effective_provider  text,
  effective_model     text,

  writer_mode         text,
  initiating_actor    text,
  effective_actor     text,
  capability_binding  text,          -- only when one actually participated; else 'not_applicable'
  runtime_build       text,

  created_at      timestamptz NOT NULL DEFAULT now()
);

-- One provenance row per (script revision, attempt): a re-drive or recovery of the SAME attempt is an
-- idempotent no-op rather than a duplicate history entry. Mirrors uq_topic_provenance_attempt.
CREATE UNIQUE INDEX IF NOT EXISTS uq_script_provenance_attempt
  ON script_provenance (script_id, revision);
CREATE INDEX IF NOT EXISTS idx_script_provenance_job ON script_provenance (job_id);
CREATE INDEX IF NOT EXISTS idx_script_provenance_slot ON script_provenance (slot_id);

-- NO BACKFILL, deliberately. Scripts produced before #357 have no recoverable manifest, authority
-- snapshot, or consumed-revision record. Inventing one would fabricate provenance that never existed;
-- historical Script evidence stays unknown and is reported as unknown.

COMMIT;
