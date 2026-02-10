-- Revert asya-gateway:004_lowercase_status_values from pg

BEGIN;

-- Revert to title case status values
UPDATE tasks SET status = 'Pending' WHERE status = 'pending';
UPDATE tasks SET status = 'Running' WHERE status = 'running';
UPDATE tasks SET status = 'Succeeded' WHERE status = 'succeeded';
UPDATE tasks SET status = 'Failed' WHERE status = 'failed';
UPDATE tasks SET status = 'Unknown' WHERE status = 'unknown';

UPDATE task_updates SET status = 'Pending' WHERE status = 'pending';
UPDATE task_updates SET status = 'Running' WHERE status = 'running';
UPDATE task_updates SET status = 'Succeeded' WHERE status = 'succeeded';
UPDATE task_updates SET status = 'Failed' WHERE status = 'failed';
UPDATE task_updates SET status = 'Unknown' WHERE status = 'unknown';

-- Restore title case constraint
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
    CHECK (status IN ('Pending', 'Running', 'Succeeded', 'Failed', 'Unknown'));

COMMIT;
