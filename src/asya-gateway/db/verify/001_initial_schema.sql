-- Verify asya-gateway:001_initial_schema on pg

BEGIN;

-- Verify tables exist
SELECT id, status, route_actors, route_current, payload, result, error, timeout_sec, deadline, created_at, updated_at
FROM tasks WHERE FALSE;

SELECT id, task_id, status, message, result, error, timestamp
FROM task_updates WHERE FALSE;

-- Verify indexes exist
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'tasks' AND indexname = 'idx_tasks_status';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'tasks' AND indexname = 'idx_tasks_created_at';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'tasks' AND indexname = 'idx_tasks_updated_at';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'tasks' AND indexname = 'idx_tasks_deadline';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'task_updates' AND indexname = 'idx_task_updates_task_id';
SELECT 1/COUNT(*) FROM pg_indexes WHERE tablename = 'task_updates' AND indexname = 'idx_task_updates_timestamp';

-- Verify function exists
SELECT 1/COUNT(*) FROM pg_proc WHERE proname = 'update_updated_at_column';

ROLLBACK;
