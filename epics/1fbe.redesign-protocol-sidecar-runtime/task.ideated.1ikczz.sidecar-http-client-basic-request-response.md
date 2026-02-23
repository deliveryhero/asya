---
title: Sidecar HTTP client — basic request/response
priority: 2 # medium
type: task
dependencies:
  - 1fbe/1iof6x
---

Replace binary framing client in sidecar with net/http over Unix socket.

Scope:
- Replace SendSocketData()/RecvSocketData() binary framing with HTTP client
- Configure net/http.Client with Unix socket dialer (net.Dial unix)
- POST /invoke with JSON body
- Parse JSON response for return-based handlers (single and fan-out)
- Handle 204 No Content (abort/empty)
- Handle 500 errors with error JSON parsing
- HTTP client timeout (default 5 minutes, configurable)
- Connection error handling (socket not ready, connection refused)
- Maintain same CallRuntime() []RuntimeResponse interface for router compatibility

Key files:
- src/asya-sidecar/internal/runtime/client.go
- src/asya-sidecar/internal/runtime/client_test.go

Unit tests required.
