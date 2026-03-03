---
title: "DB migration: tools table and new task status values"
priority: 2 # medium
type: task
---


## Objective

Create Sqitch migration `009_tools_table_and_status_values` that adds the `tools` table
and expands the task status constraint to cover all 9 A2A states. This migration
provides the schema foundation for the DB-backed tool registry (replacing YAML config)
and full A2A task lifecycle support.

## Scope

### 1. Create `tools` table (RFC Section 13.4)

Add a new `tools` table that replaces the former YAML-based `routes.yaml` ConfigMap.
The table stores both MCP tool definitions and A2A skill metadata in a single row,
with protocol-specific visibility controlled by boolean flags.

```sql
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
    a2a_examples     TEXT[] NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Column notes:
- `name` is the natural primary key, used as the tool/skill identifier across MCP,
  A2A, and CLI.
- `actor` is the single entrypoint actor name. The gateway resolves it to a queue
  name via `asya-{namespace}-{actor}`.
- `parameters` is a full JSON Schema object, passed through to MCP/A2A without
  interpretation by the gateway.
- `timeout_sec` is a per-tool timeout override; NULL means use the gateway default.
- `mcp_enabled` controls visibility in MCP `tools/list` (default true).
- `a2a_enabled` controls visibility in the A2A Agent Card skills list (default false,
  explicit opt-in).
- `a2a_tags`, `a2a_input_modes`, `a2a_output_modes`, `a2a_examples` are A2A skill
  metadata arrays used when generating the Agent Card.

### 2. Update tasks table status constraint (RFC Section 13.1)

The current status constraint (from migration `004_lowercase_status_values`) allows
only 5 values: `pending`, `running`, `succeeded`, `failed`, `unknown`. Expand it to
include all 9 states required for full A2A lifecycle support:

```sql
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check
  CHECK (status IN (
    'pending', 'running', 'succeeded', 'failed', 'unknown',
    'paused', 'canceled', 'rejected', 'auth_required'
  ));
```

New states:
- `paused` maps to A2A `INPUT_REQUIRED` (actor requests user input)
- `canceled` maps to A2A `CANCELED` (user cancels a running task)
- `rejected` maps to A2A `REJECTED` (gateway rejects the request)
- `auth_required` maps to A2A `AUTH_REQUIRED` (actor needs external authentication)

### 3. Add `updated_at` trigger for tools table

Create a trigger function (or reuse the existing one from `001_initial_schema` if
applicable) to auto-update the `updated_at` timestamp on every row modification.

## Files

All files under `src/asya-gateway/db/sqitch/`:

- `sqitch.plan` -- add the `009_tools_table_and_status_values` entry
- `deploy/009_tools_table_and_status_values.sql` -- forward migration
- `revert/009_tools_table_and_status_values.sql` -- revert (DROP TABLE tools, restore
  old constraint with 5 values)
- `verify/009_tools_table_and_status_values.sql` -- verify table exists and constraint
  is correct

## Acceptance Criteria

- `sqitch deploy` creates the `tools` table with all columns and correct defaults.
- `sqitch deploy` expands the tasks status constraint to 9 values.
- `sqitch revert` drops the `tools` table and restores the 5-value status constraint.
- `sqitch verify` passes after deploy.
- Existing data in the `tasks` table is not affected (no data migration needed; the
  new status values are additive).
