-- ==========================================================================
-- Migration 004 — M5: mandatory-review reviewer principals
-- Idempotent. The native editor + scholar are first-class principals with roles,
-- so the sign-off gates' approvers reference real IDs (BLOCK 3 principal model).
-- ==========================================================================
INSERT INTO principal (principal_id, kind, display_name_ar, display_name_en, role, module) VALUES
  ('nour',   'user', 'نور',  'Nour',   'language_reviewer', 'content'),
  ('sheikh', 'user', 'الشيخ', 'Sheikh', 'scholar',           'content')
ON CONFLICT (principal_id) DO NOTHING;
