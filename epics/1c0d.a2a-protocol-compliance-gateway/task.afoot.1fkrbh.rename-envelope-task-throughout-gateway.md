---
title: Rename envelope to task throughout gateway
priority: 2 # medium
type: task
tags:
  - pr:202
---





Refactor gateway codebase to use A2A terminology.

## Terminology Changes
- Envelope → Task
- envelope_id → task_id  
- EnvelopeStore → TaskStore
- EnvelopeStatus → TaskStatus
- envelope_updates table → task_updates table

## Files to Update
- pkg/types/envelope.go → pkg/types/task.go
- internal/envelopestore/ → internal/taskstore/
- internal/mcp/handlers.go (all handler names and types)
- internal/mcp/registry.go
- Database migrations for PostgreSQL

## Status Mapping
Current → A2A:
- pending → submitted
- running → working
- succeeded → completed
- failed → failed
- (new) → input_required, cancelled, rejected, auth_required

## Backward Compatibility
- Keep /envelopes/* routes temporarily with deprecation warning
- Add X-Deprecated header to old routes
- Plan removal in future version

## Testing
- Update all existing tests
- Verify no breaking changes in sidecar communication


---
_Migrated from beads `asya-uic`_
