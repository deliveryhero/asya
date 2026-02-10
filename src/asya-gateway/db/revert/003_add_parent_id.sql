-- Revert asya-gateway:003_add_parent_id from pg

BEGIN;

-- Drop parent_id column from tasks table
DROP INDEX IF EXISTS idx_tasks_parent_id;
ALTER TABLE tasks DROP COLUMN IF EXISTS parent_id;

COMMIT;
