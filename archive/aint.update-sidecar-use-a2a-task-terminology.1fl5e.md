---
title: Update sidecar to use A2A task terminology
status: merged
priority: 2
tags:
  - worktree:.worktrees/1c0d/1fl5rf.update-sidecar-use-a2a-task-terminology
  - branch:1c0d/1fl5rf.update-sidecar-use-a2a-task-terminology
  - pr:208
---

Update asya-sidecar to communicate with gateway using A2A task terminology.

## Current State
Sidecar uses:
- POST /envelopes/{id}/progress
- POST /envelopes/{id}/final
- GET /envelopes/{id}/active

## Target State
Sidecar uses:
- POST /tasks/{id}/progress (or internal endpoint)
- POST /tasks/{id}/final
- GET /tasks/{id}/active

## Implementation
- Update sidecar HTTP client endpoints
- Update request/response formats if changed
- Ensure backward compatibility during migration

## Files to Update
- src/asya-sidecar/internal/progress/reporter.go
- src/asya-sidecar/internal/gateway/client.go

## Testing
- Integration tests with new endpoints
- Verify sidecar-gateway communication


---
_Migrated from beads `asya-57s`_
