-- Deploy asya-gateway:007_add_partial_payload to pg

BEGIN;

-- Add partial_payload column to task_updates for persisting streaming partial events.
-- Partial events (e.g. LLM tokens) are stored here so SSE clients connecting after
-- task completion can replay them via GetUpdates.
ALTER TABLE task_updates
ADD COLUMN partial_payload JSONB;

COMMIT;
