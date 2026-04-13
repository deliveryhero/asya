---
title: "Implement GET /tasks/{id}:subscribe SSE endpoint"
status: merged
priority: 2
parent: emmc5
tags:
  - pr:202
---

Add A2A-compliant task subscription endpoint for real-time updates.

## Requirements
- GET /tasks/{task_id}:subscribe - SSE stream for task updates
- Replace current /envelopes/{id}/stream
- Follow A2A event format

## SSE Events
1. TaskStatusUpdateEvent - On state changes
2. TaskArtifactUpdateEvent - On new artifacts
3. Keepalive comments every 15 seconds

## Event Format
```
: keepalive

event: TaskStatusUpdateEvent
data: {"task_id": "...", "status": {"state": "working", "timestamp": "..."}}

event: TaskArtifactUpdateEvent
data: {"task_id": "...", "artifact": {...}}
```

## Implementation
- Refactor HandleEnvelopeStream to HandleTaskSubscribe
- Use A2A event names and format
- Historical replay on connection
- Auto-close on terminal state

## Testing
- Integration test for SSE connection
- Test historical replay
- Test keepalive
- Test stream termination


---
_Migrated from beads `asya-z80`_
