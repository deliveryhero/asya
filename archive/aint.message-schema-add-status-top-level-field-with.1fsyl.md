---
title: "Message schema: add status top-level field with lifecycle phases"
status: merged
priority: 1
parent: s62ja
---

Add 'status' as a 5th top-level field to the Asya message schema. Currently messages have: id, route, headers, payload. Add status with lifecycle phases.

Status object fields:
- phase: pending|processing|retrying|succeeded|failed
- reason: Completed|MaxRetriesExhausted|NonRetryableFailure|Timeout (only for terminal phases)
- actor: current/last actor name
- attempt: int (starts at 1, per-actor scope, resets on actor transition)
- max_attempts: int (from actor's resiliency config)
- created_at: ISO 8601 (set once at creation, never reset)
- updated_at: ISO 8601 (updated each time a sidecar picks up the message)
- error: {type, mro, message, traceback} (only during retrying/failed phases)

Changes required:
1. Sidecar router.go: initialize/update status on message receive
2. Sidecar router.go: set phase transitions (pending->processing, processing->succeeded/failed)
3. Runtime asya_runtime.py: preserve status field through processing (don't strip it)
4. Gateway: create messages with status.phase=pending, status.created_at
5. Update message validation in sidecar and runtime

Backward compatibility: messages without status field should be handled gracefully (create default status on receive).

RFC: .worktrees/rfc0/docs/rfc/error-handing/rfc-error-handing.md (Message Schema section)


---
**Close reason**: Implemented status field across sidecar, runtime, and gateway


---
_Migrated from beads `asya-l6jw`_
