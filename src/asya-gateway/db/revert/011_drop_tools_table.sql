-- Revert asya-gateway:011_drop_tools_table from pg
-- Recreates the tools table if the migration needs to be rolled back.

BEGIN;

CREATE TABLE IF NOT EXISTS tools (
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

COMMIT;
