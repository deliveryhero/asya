-- Verify asya-gateway:008_add_pause_metadata on pg

BEGIN;

-- Verify pause_metadata and remaining_timeout_sec columns exist in tasks
SELECT pause_metadata, remaining_timeout_sec
FROM tasks
WHERE FALSE;

ROLLBACK;
