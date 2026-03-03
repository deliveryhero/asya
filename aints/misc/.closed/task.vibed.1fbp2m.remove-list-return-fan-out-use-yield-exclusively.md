---
title: "Remove list-return fan-out, use yield exclusively"
priority: 2 # medium
type: task
tags:
  - type:feature
---





## Summary

Remove the legacy fan-out mechanism where a handler returns a list/tuple of payloads (each becoming a separate output message). Replace with yield-based fan-out exclusively. No backward compatibility — clean break.

## New Handler Model (2x2 Matrix)

Four handler types, sync/async orthogonal to return/yield:

| | return (one-to-one) | yield (one-to-at-least-one) |
|---|---|---|
| **sync** | `def handler(p) -> dict:` `return p` | `def handler(p) -> Generator:` `yield p` |
| **async** | `async def handler(p) -> dict:` `return p` | `async def handler(p) -> AsyncGenerator:` `yield p` |

- `return` always produces exactly ONE output message (even if the return value is a list — the list IS the payload)
- `yield` produces one message per yield (must yield at least once)
- sync and async are absolutely symmetrical in behavior

## What to Remove

### Runtime (src/asya-runtime/asya_runtime.py)
- **Payload mode (lines ~415-421)**: Remove `isinstance(payload, (list, tuple))` check that splits list returns into multiple messages. A returned list should be treated as a single payload value.
- **Envelope mode (lines ~435-445)**: Remove `isinstance(out, (list, tuple))` check. Same treatment — return value is always one message.
- **_error_response (line ~367)**: Returns `list[dict]` — simplify to return single dict.
- **Wire protocol**: Runtime currently sends a JSON array to sidecar. Change to send single JSON object for return handlers, and a streaming protocol (multiple frames) for yield handlers.

### Sidecar (src/asya-sidecar/)
- **internal/runtime/client.go (lines ~85-122)**: `CallRuntime()` always parses response as `[]RuntimeResponse`. Change to parse single `RuntimeResponse` for return handlers. For yield handlers, use multi-frame protocol.
- **internal/router/router.go (lines ~172-260)**: `handleRuntimeResponses()` loops through responses for fan-out. Simplify: single response path for return, streaming path for yield.
- **pkg/messages/message.go (lines ~13-24)**: Fan-out ID suffixing logic (`{id}-{index}`, `ParentID`). Keep for yield-based fan-out but remove the list-triggered path.

### Test Handlers (src/asya-testing/)
- **handlers/payload.py**: `fanout_handler()` returns list — convert to yield-based generator. `conditional_handler()` returns list for "fanout" action — convert to yield.

### Tests
- **src/asya-runtime/tests/test_asya_runtime.py**: `test_handle_request_fanout_list_output` (payload + envelope mode) — rewrite to test yield-based fan-out.
- **src/asya-sidecar/internal/router/router_test.go**: `TestRouter_ProcessMessage_FanOut`, `TestRouter_ProcessMessage_FanOut_CreatesGatewayTasks` — rewrite for yield protocol.
- **testing/integration/sidecar-runtime/tests/test_sidecar_with_runtime.py**: `test_fanout` — rewrite with yield handler.

### Documentation
- **docs/architecture/protocols/actor-actor.md (lines ~86-108)**: Remove "Fan-Out (Array)" section, add "Fan-Out (Yield)" section.
- **src/asya-runtime/README.md (lines ~195-202)**: Replace list-return fan-out example with yield example.
- **src/asya-sidecar/README.md (lines ~43-48)**: Remove "Array (fan-out)" from runtime response types.
- **AGENTS.md / CLAUDE.md**: Update handler documentation to show yield-based fan-out.

## Wire Protocol Change

Current: Runtime always sends JSON array `[{response1}, {response2}, ...]` over Unix socket.

New:
- **return handler**: Runtime sends single JSON object `{response}` over Unix socket.
- **yield handler**: Runtime sends multiple JSON frames, one per yield, terminated by `{"type": "end"}` frame. This aligns with the streaming protocol from the agentic compiler RFC.

## Migration Path

No backward compatibility. This is a breaking change. All existing fan-out handlers must be converted from list-return to yield before this lands.


---
**Close reason**: Streaming wire protocol implemented: runtime uses yield for fan-out, sidecar reads per-frame. All unit tests pass (Go + Python). Integration tests need Docker.


---
_Migrated from beads `asya-51j1`_
