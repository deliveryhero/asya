BEGIN;

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
  CHECK (status IN (
    'pending', 'running', 'succeeded', 'failed', 'unknown',
    'paused', 'canceled'
  ));

DROP TRIGGER IF EXISTS trg_tools_updated_at ON tools;
DROP FUNCTION IF EXISTS update_tools_updated_at();
DROP TABLE IF EXISTS tools;

COMMIT;
