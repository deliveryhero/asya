-- Revert asya-gateway:002_add_progress_tracking from pg

BEGIN;

-- Remove progress tracking from task_updates table
ALTER TABLE task_updates
DROP COLUMN IF EXISTS progress_percent,
DROP COLUMN IF EXISTS actor,
DROP COLUMN IF EXISTS task_state;

-- Remove progress tracking from tasks table
ALTER TABLE tasks
DROP COLUMN IF EXISTS progress_percent,
DROP COLUMN IF EXISTS current_actor_idx,
DROP COLUMN IF EXISTS current_actor_name,
DROP COLUMN IF EXISTS message,
DROP COLUMN IF EXISTS actors_completed,
DROP COLUMN IF EXISTS total_actors;

-- Drop index
DROP INDEX IF EXISTS idx_tasks_progress;

COMMIT;
