---
title: "Runtime: AsyncGenerator handler support"
priority: 1 # high
type: task
dependencies:
  - 1fbe/1iof6x
tags:
  - type:feature
---

Add `AsyncGenerator` handler detection to `asya_runtime.py`. The runtime already supports sync generators (`inspect.isgeneratorfunction`). This task adds the async counterpart.

## Scope

### asya_runtime.py
- Detect async generator: `inspect.isasyncgenfunction(handler)`
- Iterate: `async for event in handler(payload)` (payload mode) / `async for event in handler(message)` (envelope mode)
- Send each yielded event as a response frame (same as sync generators)
- After the HTTP protocol migration (1fbe), async generators produce SSE streams with `downstream` and `upstream` event types

## What This Is NOT

This task does NOT define the wire protocol or frame format. The wire protocol is defined by epic 1fbe (HTTP-over-Unix-socket with SSE). This task only adds async generator detection and iteration to the existing streaming handler infrastructure.

## Dependencies
- Depends on: 1fbe/1iof6x (runtime HTTP server — vibed)

## Test Plan
- Unit test: async generator yields 3 events
- Unit test: plain async handler still works (single frame)
- Unit test: sync generator still works (single frame)
- Unit test: async generator with exception mid-stream

## References
- RFC: 1ia4/rfc.md
- Epic: 1fbe.redesign-protocol-sidecar-runtime
