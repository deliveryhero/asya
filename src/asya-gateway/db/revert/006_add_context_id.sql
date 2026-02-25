-- Revert asya-gateway:006_add_context_id from pg

BEGIN;

-- Drop context_id column from tasks table
DROP INDEX IF EXISTS idx_tasks_context_id;
ALTER TABLE tasks DROP COLUMN IF EXISTS context_id;

COMMIT;
