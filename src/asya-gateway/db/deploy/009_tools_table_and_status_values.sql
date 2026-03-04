BEGIN;

CREATE TABLE tools (
    name             TEXT PRIMARY KEY,
    actor            TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    parameters       JSONB NOT NULL DEFAULT '{}',
    timeout_sec      INTEGER,
    progress         BOOLEAN NOT NULL DEFAULT false,
    mcp_enabled      BOOLEAN NOT NULL DEFAULT true,
    a2a_enabled      BOOLEAN NOT NULL DEFAULT false,
    a2a_tags         TEXT[] NOT NULL DEFAULT '{}',
    a2a_input_modes  TEXT[] NOT NULL DEFAULT '{application/json}',
    a2a_output_modes TEXT[] NOT NULL DEFAULT '{application/json}',
    route_next       TEXT[] NOT NULL DEFAULT '{}',
    a2a_examples     TEXT[] NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION update_tools_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tools_updated_at
    BEFORE UPDATE ON tools
    FOR EACH ROW
    EXECUTE FUNCTION update_tools_updated_at();

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
  CHECK (status IN (
    'pending', 'running', 'succeeded', 'failed', 'unknown',
    'paused', 'canceled', 'rejected', 'auth_required'
  ));

COMMIT;
