-- Deploy asya-gateway:004_lowercase_status_values to pg
-- Migrate status values from title case to lowercase for MCP compliance

BEGIN;

-- Update existing task status values to lowercase
UPDATE tasks SET status = 'pending' WHERE status = 'Pending';
UPDATE tasks SET status = 'running' WHERE status = 'Running';
UPDATE tasks SET status = 'succeeded' WHERE status = 'Succeeded';
UPDATE tasks SET status = 'failed' WHERE status = 'Failed';
UPDATE tasks SET status = 'unknown' WHERE status = 'Unknown';

-- Update existing task_updates status values to lowercase
UPDATE task_updates SET status = 'pending' WHERE status = 'Pending';
UPDATE task_updates SET status = 'running' WHERE status = 'Running';
UPDATE task_updates SET status = 'succeeded' WHERE status = 'Succeeded';
UPDATE task_updates SET status = 'failed' WHERE status = 'Failed';
UPDATE task_updates SET status = 'unknown' WHERE status = 'Unknown';

-- Drop old constraint and add new one with lowercase values
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
    CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'unknown'));

COMMIT;
