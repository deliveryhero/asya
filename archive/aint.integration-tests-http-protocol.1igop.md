---
title: Integration tests for HTTP protocol
status: merged
priority: 2
dependencies:
  - 1ikcz
  - 1in05
tags:
  - pr:192
reason: Integration tests verified passing with HTTP protocol - confirmed by PR CI.
---

Validation of the HTTP-over-Unix-socket protocol at component, integration, and e2e levels.

## Component tests (sidecar with mocks)

Location: `testing/component/sidecar/`

Test the sidecar HTTP client against a mock HTTP server (no real runtime needed):
- Successful request/response (single frame, JSON)
- Fan-out response (multiple frames in JSON array)
- Abort response (204 No Content)
- Error response (500 with error JSON)
- Timeout handling (mock server delays beyond `ASYA_RUNTIME_TIMEOUT` → sidecar sends to x-sump)
- 503 retry (mock returns 503 N times then 200)
- SSE streaming (downstream + upstream events)
- SSE mid-stream error

## Component tests (runtime with curl)

Location: `testing/component/runtime/`

Test the runtime HTTP server with `curl --unix-socket` (validates debuggability goal):
- Simple handler (return-based, payload mode)
- Simple handler (return-based, envelope mode)
- Generator handler (SSE stream with downstream events)
- Error handling (handler exception → 500)
- Abort handling (None return → 204)
- Class-based handlers (stateful)
- Async handlers

## Integration tests (sidecar + runtime)

Location: `testing/integration/sidecar-runtime/`

Sidecar + runtime communicating over Unix socket HTTP in Docker Compose:
- Simple handler end-to-end (payload mode)
- Simple handler end-to-end (envelope mode)
- Generator handler (fan-out via yield)
- Error handling (handler exception → x-sump routing)
- Abort handling (None return → ack, no downstream)
- Class-based handlers (stateful)
- Async handlers

## E2e tests

Location: `testing/e2e/`

Full Kubernetes scenarios (timeout + pod crash requires real pod lifecycle):
- Timeout: long-running handler → x-sump + pod restart
- 503 readiness: slow handler loading → sidecar retries → eventual success

## Key files

- `testing/component/` (new or updated)
- `testing/integration/sidecar-runtime/`
- `testing/e2e/`
