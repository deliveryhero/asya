-- Verify asya-gateway:003_add_parent_id on pg

BEGIN;

-- Verify parent_id column exists
SELECT parent_id
FROM envelopes
WHERE FALSE;

ROLLBACK;
