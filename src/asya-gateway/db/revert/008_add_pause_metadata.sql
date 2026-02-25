-- Revert asya-gateway:008_add_pause_metadata from pg

BEGIN;

ALTER TABLE tasks DROP COLUMN IF EXISTS remaining_timeout_sec;
ALTER TABLE tasks DROP COLUMN IF EXISTS pause_metadata;

COMMIT;
