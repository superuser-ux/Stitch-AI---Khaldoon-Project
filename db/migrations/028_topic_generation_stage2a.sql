-- #310 V2 Stage 2A — Topic generation: policy generation, job truth, exact provenance.
--
-- ADDITIVE, IDEMPOTENT, FORWARD-ONLY (operator ruling): these are NEW tables only. There is NO
-- rename/drop/rewrite/backfill of any operator-owned or historical value, and there is deliberately
-- NO down-migration here — rollback is code/config DISABLE with these tables left DORMANT, never a
-- DROP. Every statement is `IF NOT EXISTS` so a rerun is a non-destructive no-op. Stage 1 tables
-- (round, slot, topic, round_policy_snapshot, methodology_*, repetition_policy) are byte-untouched;
-- accepted Schedule truth is never modified by anything here.

-- ---------------------------------------------------------------------------------------------
-- topic_generation_policy — the versioned product policy for Stage 2 generation (#310 §D/§6).
--
-- Generation-versioned exactly like methodology_version / content_format_version: stable immutable
-- identity, parent/supersedes lineage, actor/reason/time, append-only history, and EXACTLY ONE
-- active generation resolved by a partial unique index. It holds the novelty/concentration/lookback/
-- exploration defaults. It is a SEPARATE seam from #184's flat repetition_policy (which stays the
-- untouched post-generation dedup safety net) — a mutable control row cannot express an immutable
-- generation lineage, so reusing it was rejected in preflight.
CREATE TABLE IF NOT EXISTS topic_generation_policy (
  policy_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  generation_no   int  NOT NULL,
  supersedes      uuid REFERENCES topic_generation_policy(policy_id),  -- parent lineage; NULL = root
  status          text NOT NULL DEFAULT 'active',                      -- active | superseded | archived
  -- versioned defaults (governed product policy; AI may recommend, only governed authority commits):
  -- Schedule-to-Topic ENTRY MODE — a governed, IMMUTABLE, versioned product-policy choice (NOT a
  -- surface branch) that selects only the TRIGGER TIMING of the SAME durable Stage 2A job:
  -- 'automatic' enqueues+dispatches Topic generation right after Schedule acceptance; 'manual' is a
  -- V2-governed authorized trigger-timing choice — it enqueues the SAME durable job in
  -- 'awaiting_trigger' for an authorized V2 Generate trigger to activate into the same canonical
  -- runner (identical pins/provenance; only timing differs). Immutable per generation (a mode change
  -- is a NEW generation, never an in-place edit). Baseline defaults to 'automatic'; an authorized
  -- tenant/org/user generation may select 'manual'. No silent fallback — an unrecognized value fails
  -- closed at resolve time.
  entry_mode      text NOT NULL DEFAULT 'automatic' CHECK (entry_mode IN ('automatic','manual')),
  novelty_lookback_days   int  NOT NULL DEFAULT 90,
  novelty_max_exclusions  int  NOT NULL DEFAULT 24,   -- bounded brief — never the full ledger (#268)
  semantic_near_threshold real NOT NULL DEFAULT 0.82,
  concentration_bounds    jsonb NOT NULL DEFAULT '{}'::jsonb,
  exploration             jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor           text NOT NULL DEFAULT 'system',
  reason          text,
  tenant_id       text NOT NULL DEFAULT 'default',
  module          text NOT NULL DEFAULT 'content',
  created_at      timestamptz NOT NULL DEFAULT now()
);
-- Exactly one active generation (fail-closed on zero/ambiguous is enforced in the engine resolver).
CREATE UNIQUE INDEX IF NOT EXISTS uq_topic_generation_policy_one_active
  ON topic_generation_policy (tenant_id, module) WHERE status = 'active';

-- ---------------------------------------------------------------------------------------------
-- generation_job — one idempotent Topic-generation job per accepted run (#310 §A).
--
-- The idempotency key is (round_id, accepted_schedule_token): first acceptance mints the job; replay/
-- reread/import/retry/legacy resolve to the SAME key and never double-trigger or backfill. Job truth
-- (queued/running/partial/failed/completed + counts + typed error) is exposed through the read model.
CREATE TABLE IF NOT EXISTS generation_job (
  job_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id        text NOT NULL REFERENCES round(round_id),
  accepted_schedule_token int NOT NULL,               -- pins the exact accepted Schedule the job serves
  stage           text NOT NULL DEFAULT 'topic',
  status          text NOT NULL DEFAULT 'queued',      -- awaiting_trigger (manual, non-drainable) |
                                                       -- queued | running | partial | failed | completed
  slots_total     int  NOT NULL DEFAULT 0,
  slots_done      int  NOT NULL DEFAULT 0,
  slots_failed    int  NOT NULL DEFAULT 0,
  trigger_source  text NOT NULL DEFAULT 'schedule_acceptance',
  error_detail    jsonb,                               -- typed error, not a scary string
  actor           text NOT NULL DEFAULT 'system',
  tenant_id       text NOT NULL DEFAULT 'default',
  module          text NOT NULL DEFAULT 'content',
  -- DURABLE EXECUTION LEASE (bounded crash recovery): a running job holds a time-bounded lease and
  -- heartbeats while it works. A drainer may reclaim a 'running' job ONLY once its lease has EXPIRED
  -- (the worker died without finishing) — never one with a fresh heartbeat (a genuinely active run).
  -- This makes dispatch at-least-once with idempotent recovery, not the earlier at-most-once.
  lease_expires_at timestamptz,                        -- when an unheartbeated 'running' job is reclaimable
  heartbeat_at     timestamptz,                        -- last progress heartbeat
  claimed_by       text,                               -- diagnostic: which worker holds the lease
  -- PINNED policy identities (immutable snapshot): resolved ONCE, scoped by the round's tenant+module,
  -- at Schedule acceptance and frozen on the job. Execution/recovery NEVER re-resolves the active
  -- policy — a generation-policy or repetition-policy change after enqueue cannot silently alter this
  -- job's novelty/allocation behaviour or its recorded provenance. NULL repetition = production default.
  topic_generation_policy_id uuid REFERENCES topic_generation_policy(policy_id),
  repetition_policy_id       uuid,                     -- lineage to the (mutable) source repetition row
  repetition_policy_snapshot jsonb,                    -- IMMUTABLE full effective repetition VALUES @ enqueue
  writer_agent               text,                     -- governed writer identity (existing 'writers' actor)
  writer_contract_version    text,                     -- governed writer contract version pinned @ enqueue
  -- AUTHORITY lineage (separate from execution): an IMMUTABLE snapshot of the exact accepted Schedule
  -- gate + ALL its approving gate_decision rows (approver principals, actor kinds, decision/revision/
  -- time, quorum, + AgentRep accountable_owner where truthfully present). Quorum may yield MULTIPLE
  -- approvers — never collapsed, and never the resolver/writer (that is execution lineage). Generic
  -- runtime control/delegation is NOT owned here: it is recorded as control_resolution='not_recorded'
  -- (the governed #21/#197 delegation slice), never approximated from principal.owner_id.
  authority_snapshot         jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
-- Forward-only, non-destructive: add the lease + pin/snapshot/writer columns to a generation_job that
-- a prior run of this migration already created without them (fresh deploys get them from CREATE).
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS heartbeat_at     timestamptz;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS claimed_by       text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS topic_generation_policy_id uuid REFERENCES topic_generation_policy(policy_id);
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS repetition_policy_id       uuid;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS repetition_policy_snapshot jsonb;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS writer_agent               text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS writer_contract_version    text;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS authority_snapshot         jsonb;
ALTER TABLE generation_job ADD COLUMN IF NOT EXISTS entry_mode                 text;  -- pinned resolved mode
-- Forward-only, behaviour-preserving: an existing operator generation created before this column
-- keeps its CURRENT behaviour (automatic) — the default backfills it, overwriting nothing meaningful.
ALTER TABLE topic_generation_policy ADD COLUMN IF NOT EXISTS entry_mode text NOT NULL DEFAULT 'automatic';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='topic_generation_policy_entry_mode_chk') THEN
    ALTER TABLE topic_generation_policy ADD CONSTRAINT topic_generation_policy_entry_mode_chk
      CHECK (entry_mode IN ('automatic','manual'));
  END IF;
END $$;
-- The idempotency guarantee: at most one job per (round, accepted token). A retry updates this row
-- and appends attempts beneath existing Topic identities — it never inserts a second job.
CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_job_round_token
  ON generation_job (round_id, accepted_schedule_token, stage);
-- Drain index: queued or lease-expired running jobs the recovery drain must find.
CREATE INDEX IF NOT EXISTS idx_generation_job_drainable
  ON generation_job (status, lease_expires_at);

-- ---------------------------------------------------------------------------------------------
-- topic_provenance — the exact per-attempt provenance tuple (#310 §E).
--
-- Keyed by (topic_id, revision) — the canonical Topic identity plus its append-only attempt/version
-- lineage that already exists on `topic`. Records RESOLVED provider/model/route/actor (not configured
-- intent), the exact pinned generation ids consumed, the novelty-brief version + input historical
-- Topic ids, the deterministic seed, and the generation-order decision evidence. A cross-format
-- variant carries its own canonical topic_id plus concept_family/variant linkage and the governing
-- repetition-policy exception.
CREATE TABLE IF NOT EXISTS topic_provenance (
  provenance_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  topic_id        uuid NOT NULL REFERENCES topic(topic_id),
  revision        int  NOT NULL DEFAULT 1,
  job_id          uuid REFERENCES generation_job(job_id),
  -- pinned generations consumed (resolved from the run, never reinterpreted):
  methodology_version       text,
  schedule_policy_snapshot  uuid,
  accepted_schedule_token   int,
  framework_version         text,
  repetition_policy_id      uuid,
  topic_generation_policy_id uuid REFERENCES topic_generation_policy(policy_id),
  writer_contract_version   text,
  -- ACTUAL execution truth (resolved, not intended):
  resolved_provider   text,
  resolved_model      text,
  execution_route     text,
  effective_actor     text,
  -- novelty + ordering evidence:
  novelty_brief_version   text,
  novelty_input_topic_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  novelty_selection_reason jsonb,
  repeat_policy_exception jsonb,               -- set only for a governed cross-format variant
  order_seed          text,
  order_decision      jsonb,
  -- cross-format variant linkage (own canonical identity; stable concept-family):
  concept_family_id   uuid,
  variant_of_topic_id uuid REFERENCES topic(topic_id),
  tenant_id       text NOT NULL DEFAULT 'default',
  created_at      timestamptz NOT NULL DEFAULT now()
);
-- One provenance row per canonical Topic ATTEMPT (topic_id + append-only revision). This is the
-- declared invariant made real: a UNIQUE index, so a re-drive/recovery of the same attempt is an
-- idempotent no-op (record_topic_provenance uses ON CONFLICT DO NOTHING), never a second row. A
-- cross-format variant carries its OWN topic_id and a rework its own revision, so both remain
-- distinct attempts under this key.
-- #310 §E — the IMMUTABLE repetition-policy value snapshot the attempt actually executed under, plus
-- the governed writer identity (writer_contract_version + effective_actor already exist on the table).
ALTER TABLE topic_provenance ADD COLUMN IF NOT EXISTS repetition_policy_snapshot jsonb;
ALTER TABLE topic_provenance ADD COLUMN IF NOT EXISTS writer_agent               text;
ALTER TABLE topic_provenance ADD COLUMN IF NOT EXISTS authority_snapshot         jsonb;
ALTER TABLE topic_provenance ADD COLUMN IF NOT EXISTS entry_mode                 text;  -- resolved mode this attempt ran under
CREATE UNIQUE INDEX IF NOT EXISTS uq_topic_provenance_attempt ON topic_provenance (topic_id, revision);
CREATE INDEX IF NOT EXISTS idx_topic_provenance_job   ON topic_provenance (job_id);
CREATE INDEX IF NOT EXISTS idx_topic_provenance_family ON topic_provenance (concept_family_id)
  WHERE concept_family_id IS NOT NULL;
