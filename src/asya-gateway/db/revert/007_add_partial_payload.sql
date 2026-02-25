-- Revert asya-gateway:007_add_partial_payload from pg

BEGIN;

ALTER TABLE task_updates DROP COLUMN IF EXISTS partial_payload;

COMMIT;
