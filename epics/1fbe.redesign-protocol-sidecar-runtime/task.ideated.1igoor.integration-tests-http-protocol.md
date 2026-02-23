---
title: Integration tests for HTTP protocol
priority: 2 # medium
type: task
dependencies:
  - 1fbe/1ikczz
  - 1ia4/1in0hv
---


End-to-end validation of the new HTTP-over-Unix-socket protocol.

Scope:
- Component tests: runtime HTTP server tested with curl (validates debuggability goal)
- Integration tests: sidecar + runtime over Unix socket HTTP in Docker Compose
- Test scenarios:
  - Simple handler (return-based, payload mode)
  - Simple handler (return-based, envelope mode)
  - Generator handler (fan-out via yield)
  - Error handling (handler exception -> 500)
  - Abort handling (None return -> 204)
  - Timeout (long-running handler -> x-sump + pod crash)
  - Class-based handlers (stateful)
  - Async handlers

Key files:
- testing/component/ (new or updated)
- testing/integration/sidecar-runtime/
