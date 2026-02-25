-- Deploy asya-gateway:006_add_context_id to pg

BEGIN;

-- Add context_id column to tasks table for A2A conversation grouping
ALTER TABLE tasks
ADD COLUMN context_id TEXT;

-- Index for finding all tasks in a conversation context
CREATE INDEX idx_tasks_context_id ON tasks(context_id) WHERE context_id IS NOT NULL;

COMMIT;
