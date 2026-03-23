-- Deploy asya-gateway:007_add_partial_payload to pg

BEGIN;

-- Add partial_payload column to task_updates for persisting streaming partial events.
-- Column retained for backward compatibility. FLY events are now ephemeral (broadcast via
-- PG LISTEN/NOTIFY) and are NOT written to this column. Only progress/status updates persist.
ALTER TABLE task_updates
ADD COLUMN partial_payload JSONB;

COMMIT;
