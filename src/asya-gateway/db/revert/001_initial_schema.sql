-- Revert asya-gateway:001_initial_schema from pg

BEGIN;

DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;
DROP FUNCTION IF EXISTS update_updated_at_column();
DROP TABLE IF EXISTS task_updates;
DROP TABLE IF EXISTS tasks;

COMMIT;
