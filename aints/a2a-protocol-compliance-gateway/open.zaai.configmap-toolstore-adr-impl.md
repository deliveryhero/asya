---
title: Migrate toolstore from DB to ConfigMap-mounted YAML + fsnotify hot-reload (ADR impl)
priority: 2 # medium
---

Implement the accepted ADR (`adr.configmap-flow-registry.md`): replace the
PostgreSQL-backed `tools` table with a ConfigMap-mounted `flows.yaml` file
read by the gateway at startup, with fsnotify hot-reload.

**ADR reference**: `adr.configmap-flow-registry.md` (accepted 2026-03-06)

## What changes

### toolstore/registry.go
- Remove `pgxpool.Pool` field and all SQL queries
- Replace `NewRegistry(ctx, pool)` with `NewRegistryFromDir(dir string)` that
  reads all `*.yaml` files in the mounted config directory
- Replace `Refresh(ctx)` with `LoadFromDir(dir)` — parses YAML, updates
  `atomic.Value` cache
- Remove `Upsert()` — write path is gone (ConfigMap is write-protected for gateway)
- Keep `All()`, `GetByName()`, `MCPTools()`, `A2ASkills()` unchanged

### toolstore/types.go
- Add `FlowConfig` struct matching the `flows.yaml` schema (ADR §schema):
  `Name`, `Entrypoint`, `Description`, `TimeoutSec`, `MCP *MCPConfig`,
  `A2A *A2AConfig`
- `MCPConfig`: `InputSchema json.RawMessage`
- `A2AConfig`: `Tags`, `Examples`, `InputModes`, `OutputModes`
- Keep `Tool` as the internal type; `FlowConfig` is the YAML surface

### toolstore/handler.go
- Remove `handleRegister` (POST handler) — write path is kubectl
- Keep `handleList` (GET handler) for `GET /mesh/expose` read-only visibility
- `HandleExpose` now only serves GET; return 405 on POST

### toolstore/watcher.go (new, ~30 LOC)
- fsnotify watcher on the mounted config directory
- Debounce 500ms for rapid kubelet write bursts
- On CREATE/WRITE/REMOVE: call `LoadFromDir()`, log reload at INFO level
- On invalid YAML: log error, keep previous valid cache (no crash)

### db/sqitch
- Remove migration `009_tools_table_and_status_values` (drop `tools` table)
  OR: leave the table in place and just stop writing to it (safer for rollback)
  Recommended: keep migration, add `010_drop_tools_table` that DROPs it

### cmd/gateway/main.go
- Replace `toolstore.NewRegistry(ctx, pool)` with
  `toolstore.NewRegistryFromDir(os.Getenv("ASYA_CONFIG_PATH"))`
- Start watcher goroutine after registry init

## flows.yaml schema (ADR §schema)

```yaml
flows:
  - name: extract-text
    entrypoint: text-extractor
    description: "Extract text from PDF"
    mcp:
      inputSchema:
        type: object
        properties:
          url: { type: string }
        required: [url]

  - name: analyze-doc
    entrypoint: doc-analyzer
    description: "Analyze document themes"
    timeout: 300
    mcp:
      inputSchema: {...}
    a2a:
      tags: [analysis, nlp]
      examples: ["Analyze this quarterly report for revenue trends"]
```

## What stays unchanged

- `Registry` interface: `All()`, `GetByName()`, `MCPTools()`, `A2ASkills()`
- In-memory atomic cache pattern (`atomic.Value`)
- MCP server, A2A handler, task store, queue client
- PostgreSQL for task state (tasks table untouched)

## Testing

- Unit: `NewRegistryFromDir` loads YAML, parses all flow fields correctly
- Unit: malformed YAML → error, previous cache preserved
- Unit: YAML with neither `mcp:` nor `a2a:` → validation error
- Unit: `MCPTools()` returns only flows with `mcp:` present
- Unit: `A2ASkills()` returns only flows with `a2a:` present
- Unit: watcher debounce fires reload after 500ms of quiescence
- Component: gateway starts with YAML config, Agent Card reflects skills
- Component: update YAML file → reload within 1s → Agent Card updated

## Implementation estimate

~80 LOC Go (50 YAML loader + 30 watcher) + ~30 LOC removed (SQL queries,
POST handler) + unit tests.
