-- ==========================================================================
-- M9 · Block B1 — Directive packages (the inter-stage handoff contract)
-- Additive + idempotent. A directive is the structured package one stage hands
-- the next (ARCHITECTURE.md "Inter-stage handoff = directive propagation").
-- Edges carry directives; each emission is also an audit event (handoff = memory).
-- ==========================================================================
CREATE TABLE IF NOT EXISTS directive (
  directive_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id        text NOT NULL REFERENCES slot(slot_id),
  schema_version text NOT NULL DEFAULT '1.0',
  type           text NOT NULL,                 -- strategy_directive | topic_directive | production_directive
  from_stage     text,                          -- stage that emitted it (null = origin)
  to_stage       text NOT NULL,                 -- stage that consumes it
  payload        jsonb NOT NULL,                -- the six-field package (intent bilingual)
  revision       int  NOT NULL DEFAULT 1,       -- ties to the topic/script revision it carries
  produced_by    text,                          -- principal that caused the handoff
  tenant_id      text NOT NULL DEFAULT 'default',
  module         text NOT NULL DEFAULT 'content',
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_directive_slot      ON directive(slot_id);
CREATE INDEX IF NOT EXISTS idx_directive_to_stage  ON directive(slot_id, to_stage);
