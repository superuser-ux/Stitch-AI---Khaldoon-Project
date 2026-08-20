-- ==========================================================================
-- M9 — cyclic co-creation + LINEAR version navigation. Additive + idempotent.
--   * revisions are append-only & immutable (v1->v2->v3…), each with its comment + summary.
--   * an APPROVED-REVISION pointer: approve records WHICH revision is approved; the downstream
--     directive carries that exact revision (you may approve v2 even if v3 exists).
--   * restore/rework-from vN: a new HEAD copied from vN (provenance base_revision=N) — linear,
--     no version tree.
-- ==========================================================================

-- which artifact revision an approve targets (NULL = the head/latest at decision time)
ALTER TABLE gate_decision ADD COLUMN IF NOT EXISTS revision int;

-- provenance: the revision this one was reworked/restored FROM (NULL = original)
ALTER TABLE topic  ADD COLUMN IF NOT EXISTS base_revision int;
ALTER TABLE script ADD COLUMN IF NOT EXISTS base_revision int;

-- the approved-revision pointer (one per artifact per slot). The downstream stage reads THIS.
CREATE TABLE IF NOT EXISTS slot_approval (
  slot_id    text NOT NULL REFERENCES slot(slot_id),
  artifact   text NOT NULL,                 -- topic | script
  revision   int  NOT NULL,
  approver   text,
  actor_kind text NOT NULL DEFAULT 'user',
  tenant_id  text NOT NULL DEFAULT 'default',
  at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (slot_id, artifact)
);
