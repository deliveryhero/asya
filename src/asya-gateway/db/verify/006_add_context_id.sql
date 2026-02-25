-- Verify asya-gateway:006_add_context_id on pg

BEGIN;

-- Verify context_id column exists
SELECT context_id
FROM tasks
WHERE FALSE;

ROLLBACK;
