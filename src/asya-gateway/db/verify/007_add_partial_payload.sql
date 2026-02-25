-- Verify asya-gateway:007_add_partial_payload on pg

BEGIN;

-- Verify partial_payload column exists in task_updates
SELECT partial_payload
FROM task_updates
WHERE FALSE;

ROLLBACK;
