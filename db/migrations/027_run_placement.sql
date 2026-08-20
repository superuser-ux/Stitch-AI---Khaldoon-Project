-- #304 — the minimum authoritative absolute run placement.
--
-- WHY THIS EXISTS: before this migration a round carried a DURATION and TIMES-OF-DAY
-- (period_len_days, posts_per_day, post_times) but no start, and its slots carried only a RELATIVE
-- day index (1..period_len_days). The one absolute timestamp on the row was created_at — which is
-- when the record was written, NOT when the campaign runs. A truthful run calendar is impossible
-- from that, and #304 explicitly forbids displaying created_at as the scheduled window.
--
-- SHAPE: exactly one authoritative start. Everything else derives without a second placement model:
--     window        = [starts_on, starts_on + period_len_days)
--     slot datetime = starts_on + (slot.day - 1) at slot.time_uae
-- Canonical slot placement (slot.day, slot.time_uae) is NOT duplicated here and never moves when a
-- run is placed or re-placed.
--
-- NULLABLE ON PURPOSE (#304 ruling A, mirroring #292's "legacy by absence"): rounds created before
-- this migration have no authoritative placement and must render as EXPLICITLY UNPLACED. Back-filling
-- from created_at would invent schedule truth and rewrite existing run evidence — both prohibited.
-- There is deliberately no UPDATE here: this migration only adds the seam.
--
-- OPTIONAL AT THE API (#304 ruling B): V1's New Run form has no placement field. A NOT NULL column
-- would break V1 creation, which is a named hard stop. V2's governed form supplies the placement.
ALTER TABLE round ADD COLUMN IF NOT EXISTS starts_on date;

COMMENT ON COLUMN round.starts_on IS
  '#304 — authoritative absolute start of the campaign window. NULL = never governed-placed (legacy '
  'or V1-created); render as explicitly unplaced. NEVER derive from created_at. Window is '
  '[starts_on, starts_on + period_len_days); a slot''s absolute datetime is starts_on + (day-1) at '
  'time_uae. Placement changes are governed: round lock + combined schedule_token + schedule_review '
  'authority + append-only audit, and are frozen once any slot is downstream-advanced.';

-- Calendar reads are windowed by placement; unplaced rounds are excluded from the placed index by
-- the partial predicate rather than by a sentinel date.
CREATE INDEX IF NOT EXISTS idx_round_starts_on ON round (starts_on) WHERE starts_on IS NOT NULL;
