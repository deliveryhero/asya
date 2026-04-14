---
title: Implement tool registry and /mesh/expose REST API
status: merged
priority: 2
dependencies:
  - 1qtb
tags:
  - pr:257
---

## Objective

Replace the YAML-based static tool configuration (`config.LoadConfig()`,
`routes.yaml` ConfigMap) with a DB-backed tool registry and REST API. The registry
serves as the single source of truth for both MCP tools and A2A skills, with
protocol-specific visibility controlled by `mcp_enabled` and `a2a_enabled` flags.
This implements RFC Section 8.4 (Registration API).

## Scope

### 1. Create `internal/toolstore/` package (RFC Section 8.4)

Create a new package `src/asya-gateway/internal/toolstore/` with a `ToolRegistry`
struct that wraps the `tools` database table (created by migration 009 in task
`1c0d/1qtbxr`).

```go
type Tool struct {
    Name           string         `json:"name" db:"name"`
    Actor          string         `json:"actor" db:"actor"`
    Description    string         `json:"description" db:"description"`
    Parameters     json.RawMessage `json:"parameters" db:"parameters"`
    TimeoutSec     *int           `json:"timeout_sec,omitempty" db:"timeout_sec"`
    Progress       bool           `json:"progress" db:"progress"`
    MCPEnabled     bool           `json:"mcp_enabled" db:"mcp_enabled"`
    A2AEnabled     bool           `json:"a2a_enabled" db:"a2a_enabled"`
    A2ATags        []string       `json:"a2a_tags,omitempty" db:"a2a_tags"`
    A2AInputModes  []string       `json:"a2a_input_modes,omitempty" db:"a2a_input_modes"`
    A2AOutputModes []string       `json:"a2a_output_modes,omitempty" db:"a2a_output_modes"`
    A2AExamples    []string       `json:"a2a_examples,omitempty" db:"a2a_examples"`
    CreatedAt      time.Time      `json:"created_at" db:"created_at"`
    UpdatedAt      time.Time      `json:"updated_at" db:"updated_at"`
}
```

### 2. In-memory cache via `atomic.Value` (RFC Section 8.4.4)

The registry maintains a thread-safe in-memory snapshot of all tools for fast reads.
After each mutation (POST), the gateway reloads the full tool list from the DB into
an `atomic.Value`. In-flight requests complete with the old registry; new requests
use the updated one.

```go
type ToolRegistry struct {
    tools atomic.Value // *[]Tool
    db    *sql.DB
}

func (r *ToolRegistry) Refresh() error {
    tools, err := r.loadFromDB()
    if err != nil { return err }
    r.tools.Store(&tools)
    return nil
}
```

Provide filtered accessor methods:
- `MCPTools() []Tool` -- returns tools where `mcp_enabled = true`
- `A2ASkills() []Tool` -- returns tools where `a2a_enabled = true`
- `GetByName(name string) (*Tool, bool)` -- lookup by primary key from cache

### 3. REST API endpoints (RFC Section 8.4.1-8.4.3)

#### `POST {base}/mesh/expose` -- Register/update a tool (upsert)

Accepts a JSON body matching the `Tool` struct. Performs an `INSERT ... ON CONFLICT
(name) DO UPDATE` (upsert) against the `tools` table. After successful upsert, calls
`Refresh()` to update the in-memory cache.

Request body (RFC Section 8.4.2):
```json
{
  "name": "analyze-document",
  "actor": "start-analysis",
  "description": "Analyze documents for key themes and sentiment",
  "parameters": { "type": "object", "properties": { ... }, "required": [...] },
  "timeout_sec": 300,
  "progress": true,
  "mcp_enabled": true,
  "a2a": {
    "enabled": true,
    "tags": ["analysis", "nlp"],
    "input_modes": ["application/json", "application/pdf"],
    "output_modes": ["application/json"],
    "examples": ["Analyze this quarterly report"]
  }
}
```

Response: `201 Created` (new) or `200 OK` (updated) with the tool summary.

#### `GET {base}/mesh/expose` -- List all registered tools (RFC Section 8.4.3)

Returns a JSON array of all tools (unfiltered). MCP and A2A consumers apply their
own filters (`mcp_enabled`, `a2a_enabled`) when building their respective tool
lists and Agent Cards.

### 4. Remove YAML config loading (RFC Section 8.4.6)

Remove the following components that are superseded by the DB-backed registry:

- `config.LoadConfig()` call from `src/asya-gateway/cmd/gateway/main.go`
- `ASYA_CONFIG_PATH` environment variable handling
- `routes-configmap.yaml` from `deploy/helm-charts/asya-gateway/templates/` (if it
  exists)
- `src/asya-gateway/internal/config/routes.go` -- route template resolution, `Config`
  struct, `Tool` struct, `RouteSpec`, `ToolDefaults`, `ToolOptions`, `Parameter`,
  `Validate()`, and `GetActors()` logic
- `src/asya-gateway/internal/config/loader.go` -- `LoadConfig()`, `LoadFromFile()`,
  `LoadFromDir()`, `MergeConfigs()`
- Associated test files (`loader_test.go`, `examples_test.go`)

Update callers that currently depend on `config.Config`:
- `internal/a2a/handler.go` -- `NewHandler` takes `*config.Config`; replace with
  `*toolstore.ToolRegistry`
- `internal/mcp/` -- MCP handlers that read tool definitions from config; update to
  read from the registry's `MCPTools()` method

### 5. Wire into gateway server

- Register the `POST` and `GET` handlers on the `/mesh/expose` route in the gateway's
  HTTP mux (alongside existing `/mesh/{id}/progress`, `/mesh/{id}/final`, etc.)
- Initialize `ToolRegistry` with the DB connection during gateway startup
- Call `Refresh()` at startup to populate the in-memory cache from existing DB rows

### 6. Unit tests (RFC Section 15.1)

Create `src/asya-gateway/internal/toolstore/registry_test.go` covering:
- Upsert: insert new tool, update existing tool (verify `updated_at` changes)
- List: returns all tools, empty list when no tools exist
- Filtered accessors: `MCPTools()` returns only `mcp_enabled=true`, `A2ASkills()`
  returns only `a2a_enabled=true`
- `GetByName`: found and not-found cases
- In-memory refresh: after upsert, cache reflects new state
- Concurrent access: multiple goroutines reading while one writes (no races)
- JSON parameters: round-trip JSONB serialization of complex JSON Schema objects

## Files

- `src/asya-gateway/internal/toolstore/registry.go` -- new file
- `src/asya-gateway/internal/toolstore/registry_test.go` -- new file
- `src/asya-gateway/cmd/gateway/main.go` -- remove `LoadConfig`, wire registry
- `src/asya-gateway/internal/config/loader.go` -- remove or gut
- `src/asya-gateway/internal/config/routes.go` -- remove or gut
- `src/asya-gateway/internal/a2a/handler.go` -- update to use `ToolRegistry`
- `src/asya-gateway/internal/mcp/` -- update tool source

## Dependencies

- **T1** (`1c0d/1qtbxr`): The `tools` table must exist before this task can write to
  it. The migration must be deployed first.

## Acceptance Criteria

- `POST {base}/mesh/expose` creates and updates tools in the DB.
- `GET {base}/mesh/expose` returns the full tool list as JSON.
- In-memory cache updates after each mutation, verified by immediate GET.
- MCP and A2A read from the same registry with appropriate filters.
- No YAML config files, `LoadConfig()`, or `ASYA_CONFIG_PATH` remain in the codebase.
- All unit tests pass, including concurrent access tests.
- `go build ./...` succeeds with no references to removed config types.
