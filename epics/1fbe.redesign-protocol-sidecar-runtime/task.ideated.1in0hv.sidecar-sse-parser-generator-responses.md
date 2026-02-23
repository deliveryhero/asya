---
title: Sidecar SSE parser for generator responses
priority: 2 # medium
type: task
dependencies:
  - 1ia4/1i6yzk
  - 1fbe/1ikczz
---


Add SSE stream parser to sidecar HTTP client for generator handler responses.

Scope:
- Detect Content-Type: text/event-stream in response
- Parse SSE events: downstream, upstream, done, error
- Map downstream events to RuntimeResponse slice (same as current fan-out)
- Forward upstream partial events to gateway (token streaming)
- Handle done event as stream termination
- Handle error events mid-stream
- Timeout handling for long-running generators

Key files:
- src/asya-sidecar/internal/runtime/client.go (CallRuntime function)
- src/asya-sidecar/internal/router/router.go (handleRuntimeResponses)

Unit tests required.
