---
title: Implement AG-UI event streaming endpoint
status: open
priority: 2
parent: emmc5
---

Add AG-UI compatible event streaming for frontend integration.

## Overview
AG-UI (Agent-User Interaction Protocol) enables rich frontend integration with frameworks like CopilotKit. This allows Asya to stream events directly to user-facing applications.

## Endpoint
GET /ag-ui/stream?thread_id=xxx&run_id=yyy
Content-Type: text/event-stream

## AG-UI Event Types to Implement

### Lifecycle Events
- RunStarted - When task begins
- RunFinished - When task completes
- RunError - When task fails
- StepStarted/StepFinished - Actor transitions

### Text Message Events  
- TextMessageStart - New message from agent
- TextMessageContent - Streaming text delta
- TextMessageEnd - Message complete

### Tool Call Events
- ToolCallStart - Tool invocation begins
- ToolCallArgs - Streaming tool arguments
- ToolCallEnd - Tool invocation complete
- ToolCallResult - Tool output

### State Events
- StateSnapshot - Full state initialization
- StateDelta - Incremental state updates (JSON Patch)

## Event Format
```
event: TEXT_MESSAGE_CONTENT
data: {"message_id": "msg-1", "delta": "Hello world"}
```

## Implementation
- Add /ag-ui/stream handler
- Map Asya envelope updates to AG-UI events
- Support thread_id and run_id query params
- Implement keepalive comments

## Testing
- Integration test with SSE client
- Test all 17 event types
- Test with CopilotKit frontend

## References
- https://docs.ag-ui.com/
- https://github.com/ag-ui-protocol/ag-ui


---
## Notes

## AG-UI Protocol Research (2026-01-28)

### Overview
AG-UI (Agent-User Interaction Protocol) is an open, lightweight, event-based protocol that standardizes how AI agents connect to user-facing applications. Developed by CopilotKit, now under Linux Foundation governance.

### The 17 AG-UI Event Types

#### Lifecycle Events (5)
1. `RunStarted` - Signals agent execution begins
2. `RunFinished` - Marks successful completion
3. `RunError` - Indicates execution failure
4. `StepStarted` - Begins a sub-task (optional)
5. `StepFinished` - Completes a sub-task

#### Text Message Events (3)
6. `TextMessageStart` - Initiates a new message
7. `TextMessageContent` - Streams text chunks (delta)
8. `TextMessageEnd` - Closes message transmission

#### Tool Call Events (4)
9. `ToolCallStart` - Begins external tool invocation
10. `ToolCallArgs` - Streams function arguments (delta)
11. `ToolCallEnd` - Completes tool execution
12. `ToolCallResult` - Returns tool output

#### State Management Events (3)
13. `StateSnapshot` - Full JSON state initialization
14. `StateDelta` - Incremental changes (RFC6902 JSON Patch)
15. `MessagesSnapshot` - Conversation history sync (optional)

#### Special Events (2)
16. `RawEvent` - External system passthrough
17. `CustomEvent` - Application-specific extensions

### Base Event Structure
```json
{
  "type": "EventType",
  "timestamp": 1234567890,
  "rawEvent": null
}
```

### Example Event Payloads

**RunStarted:**
```json
{"type": "RUN_STARTED", "thread_id": "thread-123", "run_id": "run-456"}
```

**TextMessageContent:**
```json
{"type": "TEXT_MESSAGE_CONTENT", "message_id": "msg-789", "delta": "Hello world"}
```

**ToolCallStart:**
```json
{"type": "TOOL_CALL_START", "tool_call_id": "tool-001", "tool_call_name": "fetch_weather"}
```

**StateDelta (JSON Patch):**
```json
{
  "type": "STATE_DELTA",
  "delta": [
    {"op": "replace", "path": "/score", "value": 42},
    {"op": "replace", "path": "/current_step", "value": "analyzing"}
  ]
}
```

### Typical Event Flow
```
RUN_STARTED 
→ STATE_SNAPSHOT 
→ TEXT_MESSAGE_START 
→ TEXT_MESSAGE_CONTENT (repeated)
→ TEXT_MESSAGE_END 
→ TOOL_CALL_START 
→ TOOL_CALL_ARGS 
→ TOOL_CALL_END 
→ TOOL_CALL_RESULT 
→ STATE_DELTA 
→ RUN_FINISHED
```

### Transport Mechanisms
- Server-Sent Events (SSE)
- WebSockets
- Webhooks
- Custom transports

### Framework Support
- CopilotKit (original developer)
- Microsoft Agent Framework
- LangGraph
- CrewAI
- Google ADK
- Pydantic AI

### References
- https://docs.ag-ui.com/
- https://github.com/ag-ui-protocol/ag-ui
- https://docs.copilotkit.ai/ag-ui-protocol


---
_Migrated from beads `asya-0wr`_
