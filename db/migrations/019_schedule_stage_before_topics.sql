-- Introduce a confirmed-schedule checkpoint before topic-title generation.
ALTER TYPE slot_status ADD VALUE IF NOT EXISTS 'SCHEDULE_APPROVED' AFTER 'RESERVED';
