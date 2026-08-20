-- ==========================================================================
-- Migration 006 — Unified Actor Model "adopt-now" seams (BUILD_STATE concept)
-- Idempotent. Add the autonomy axes + scope as DATA on the principal model now,
-- defaulting to the SAFEST values. No behavior wired yet (only the review-discretion
-- path reads policy today); the full policy-resolution engine is M8+. This keeps the
-- seam so later work is config/data, not a migration + backfill on a live registry.
--
-- Three SEPARATE axes + scope (per the Unified Actor Model):
--   autonomy_level — how independently it acts. Ladder (least -> most):
--     propose_only | recommend | act_with_approval | act_and_notify | autonomous
--     Default 'propose_only' (safest). Agents NEVER self-escalate; raising it is an
--     explicit, scoped, reversible ADMIN action.
--   capabilities — tools/skills/models it CAN use (capability matrix). Default [] (none).
--   permissions  — what it's ALLOWED to do (RBAC/ABAC). Default [] (least privilege).
--   scope        — tenant / module / workflow / stage it operates within. Default {} (narrowest).
-- ==========================================================================
ALTER TABLE principal ADD COLUMN IF NOT EXISTS autonomy_level text  NOT NULL DEFAULT 'propose_only';
ALTER TABLE principal ADD COLUMN IF NOT EXISTS capabilities    jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE principal ADD COLUMN IF NOT EXISTS permissions     jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE principal ADD COLUMN IF NOT EXISTS scope           jsonb NOT NULL DEFAULT '{}'::jsonb;
