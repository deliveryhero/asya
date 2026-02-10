-- Deploy asya-gateway:003_add_parent_id to pg

BEGIN;

-- Add parent_id column to tasks table for fanout traceability
ALTER TABLE tasks
ADD COLUMN parent_id TEXT;

-- Index for finding all fanout children of a parent task
CREATE INDEX idx_tasks_parent_id ON tasks(parent_id) WHERE parent_id IS NOT NULL;

COMMIT;
