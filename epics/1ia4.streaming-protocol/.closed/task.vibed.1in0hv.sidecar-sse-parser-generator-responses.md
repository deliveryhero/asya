---
title: Sidecar SSE parser for generator responses
priority: 2 # medium
type: task
tags:
  - pr:205
dependencies:
  - 1ia4/1i6yzk
  - 1fbe/1ikczz
---



Add SSE stream parser to sidecar HTTP client for generator handler responses.

## Scope

- Detect `Content-Type: text/event-stream` in runtime response
- Parse SSE events: `downstream`, `upstream`, `done`, `error`
- Map `downstream` events to `RuntimeResponse` slice (same as current fan-out)
- Collect `upstream` events separately (forwarded to gateway by task 1fpgp1)
- Handle `done` event as stream termination
- Handle `error` events mid-stream (route original message to x-sump)
- Timeout handling for long-running generators

## Key Files

- `src/asya-sidecar/internal/runtime/client.go` (CallRuntime function)
- `src/asya-sidecar/internal/router/router.go` (handleRuntimeResponses)

## References

- RFC: 1ia4/rfc.md
- Epic: 1fbe.redesign-protocol-sidecar-runtime (epic.md contains full SSE protocol spec)

Unit tests required.
