---
title: "Implement POST /messages:stream endpoint"
status: merged
priority: 2
tags:
  - pr:202
---

Add A2A streaming message endpoint with SSE response.

## Requirements
- POST /messages:stream - Send message, receive SSE stream
- Same request format as /messages
- Response: SSE stream with TaskStatusUpdateEvent and TaskArtifactUpdateEvent

## SSE Event Types
1. TaskStatusUpdateEvent - State changes (submitted→working→completed)
2. TaskArtifactUpdateEvent - Output artifacts from actors
3. Partial text events - Streaming text from LLM actors

## Event Format
```
event: TaskStatusUpdateEvent
data: {"task_id": "...", "status": {"state": "working"}, "message": {...}}

event: TaskArtifactUpdateEvent  
data: {"task_id": "...", "artifact": {"artifact_id": "...", "parts": [...]}}
```

## Implementation
- Combine current /envelopes/{id}/stream logic with message creation
- Create task, immediately start SSE stream
- Forward streaming events from actors
- Close stream on terminal state

## Headers
- Content-Type: text/event-stream
- Cache-Control: no-cache
- Connection: keep-alive

## Testing
- Integration test for SSE stream
- Test event ordering
- Test stream termination on completion


_Migrated from beads `asya-ey0`_
