---
title: Map Asya events to AG-UI event types
status: open
priority: 2 # medium
type: task
dependencies:
  - misc/1fkrbh
---



Create mapping layer between Asya internal events and AG-UI protocol events.

## Mapping Table

### Lifecycle Events
| Asya Event | AG-UI Event |
|------------|-------------|
| Task created | RunStarted |
| Task completed | RunFinished |
| Task failed | RunError |
| Actor started | StepStarted |
| Actor completed | StepFinished |

### Text Message Events
| Asya Event | AG-UI Event |
|------------|-------------|
| Streaming start | TextMessageStart |
| Streaming chunk | TextMessageContent |
| Streaming end | TextMessageEnd |

### Tool Call Events
| Asya Event | AG-UI Event |
|------------|-------------|
| Function call start | ToolCallStart |
| Function arguments | ToolCallArgs |
| Function call end | ToolCallEnd |
| Function response | ToolCallResult |

### State Events
| Asya Event | AG-UI Event |
|------------|-------------|
| Full envelope state | StateSnapshot |
| Progress update | StateDelta |

## Implementation
- Create internal/agui/mapper.go
- Implement event transformation functions
- Support JSON Patch format for StateDelta
- Handle message_id generation

## Testing
- Unit test for each mapping
- Verify JSON format compliance


---
## Notes

## AG-UI Event Mapping Research (2026-01-28)

### Protocol Relationship
AG-UI sits between agent backends and user-facing frontends:
- MCP = Agent ↔ Tool
- A2A = Agent ↔ Agent  
- AG-UI = Agent ↔ User

### Asya → AG-UI Event Mapping

#### Lifecycle Events
| Asya Internal | AG-UI Event | Trigger |
|---------------|-------------|---------|
| Task status: pending→running | RunStarted | Task queued to first actor |
| Task status: →completed | RunFinished | happy-end reports success |
| Task status: →failed | RunError | error-end reports failure |
| Actor index changes | StepStarted | Sidecar reports new actor |
| Actor completes | StepFinished | Sidecar reports actor done |

#### Text Message Events
| Asya Internal | AG-UI Event | Trigger |
|---------------|-------------|---------|
| Streaming event start | TextMessageStart | Actor begins text output |
| Streaming chunk | TextMessageContent | Actor yields partial text |
| Streaming complete | TextMessageEnd | Actor text stream done |

#### Tool Call Events
| Asya Internal | AG-UI Event | Trigger |
|---------------|-------------|---------|
| function_call event | ToolCallStart | ADK agent calls tool |
| function args | ToolCallArgs | Streaming tool arguments |
| function_call complete | ToolCallEnd | Tool execution starts |
| function_response | ToolCallResult | Tool returns result |

#### State Events
| Asya Internal | AG-UI Event | Trigger |
|---------------|-------------|---------|
| Initial envelope state | StateSnapshot | Client connects |
| Progress update | StateDelta | Sidecar progress report |

### Implementation Notes

1. **Message ID Generation**: Generate unique message_id for each text stream
2. **Thread/Run Mapping**: 
   - thread_id = context_id (conversation)
   - run_id = task_id (single execution)
3. **StateDelta Format**: Use RFC6902 JSON Patch for incremental updates
4. **Keepalive**: Send SSE comment every 15 seconds

### Current Asya Events (from sidecar)
```go
// Progress update from sidecar
type ProgressUpdate struct {
    ID              string
    Actors          []string
    CurrentActorIdx int
    Status          string  // received|processing|completed
    Message         string
}
```

### Target AG-UI Events
```go
type AGUIEvent struct {
    Type      string      `json:"type"`
    Timestamp int64       `json:"timestamp,omitempty"`
    // Event-specific fields...
}
```

### References
- https://www.copilotkit.ai/blog/master-the-17-ag-ui-event-types-for-building-agents-the-right-way


---
_Migrated from beads `asya-qyu`_
