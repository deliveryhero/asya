---
title: Runtime HTTP server — basic request/response
status: merged
priority: 2
tags:
  - worktree:1fbe.redesign-protocol-sidecar-runtime/1iof6x.1iof6x.runtime-http-server-basic-request-response
  - pr:189
---

Replace binary socket listener in asya_runtime.py with HTTP server on Unix socket.

Scope:
- Replace _recv_exact() / _send_message() binary framing with HTTP server
- POST /invoke endpoint accepting same message JSON format
- JSON response body for return-based handlers (single and fan-out)
- 204 No Content for abort (handler returns None)
- 500 Internal Server Error with error JSON for handler exceptions
- Keep same handler execution logic (payload mode, envelope mode)
- Unix socket listener (same socket path)
- Zero external dependencies constraint — use stdlib http.server or raw asyncio

Key files:
- src/asya-runtime/asya_runtime.py (lines 228-611)

Unit tests required.
