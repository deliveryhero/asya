---
title: "Unify terminology: task=A2A, tool=MCP, envelope=mesh"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/misc/oihm.unify-terminology-task-a2a-tool-mcp-envelope-mesh
  - branch:misc/oihm.unify-terminology-task-a2a-tool-mcp-envelope-mesh
  - pr:325
---



## Problem

The codebase uses the word "task" inconsistently. Currently `types.Task` in `src/asya-gateway/pkg/types/task.go` is a gateway-internal tracking record for any envelope in flight through the actor mesh — it is created by both A2A and MCP paths and updated by sidecar `/mesh/` callbacks.

The desired naming convention:
- **task** → A2A protocol concept only (A2A has Tasks, task IDs, task state machine)
- **tool** → MCP protocol concept only (MCP has Tools, tool calls, tool results)
- **envelope** → actor mesh wire format (what travels through queues between actors)

## Scope

1. Rename `types.Task` → something like `types.EnvelopeRecord` or `types.TrackingRecord` — the internal gateway object tracking one envelope's journey
2. Rename `TaskStore`, `TaskUpdate`, `ProgressUpdate`, `CreateTaskRequest` accordingly
3. Audit all uses of "task" in handler names, log messages, URL paths (`/mesh/{id}` is fine — the `/tasks` path may need review), and comments
4. Ensure A2A-specific code (in `internal/a2a/`) still uses "task" for A2A protocol objects (`a2alib.Task`, task IDs from A2A requests)
5. Ensure MCP-specific code uses "tool" for MCP protocol objects
6. Update docs and test fixtures to match

## Files to audit

- `src/asya-gateway/pkg/types/task.go`
- `src/asya-gateway/internal/taskstore/`
- `src/asya-gateway/internal/mcp/handlers.go`
- `src/asya-gateway/internal/a2a/executor.go`, `store_adapter.go`, `blocking.go`
- `src/asya-gateway/internal/consumer/consumer.go`
- `src/asya-gateway/internal/queue/`
