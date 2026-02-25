-- Deploy asya-gateway:008_add_pause_metadata to pg

BEGIN;

-- Add pause_metadata column for storing pause-related metadata (e.g., pause_id, pause_at timestamp).
-- Add remaining_timeout_sec column for tracking remaining timeout duration when a task is paused.
ALTER TABLE tasks
ADD COLUMN pause_metadata JSONB,
ADD COLUMN remaining_timeout_sec DOUBLE PRECISION;

COMMIT;
