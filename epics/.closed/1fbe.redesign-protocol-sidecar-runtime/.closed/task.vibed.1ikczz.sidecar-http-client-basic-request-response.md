---
title: Sidecar HTTP client — basic request/response
priority: 2 # medium
type: task
tags:
  - pr:192
dependencies:
  - 1fbe/1iof6x
  - 1fbe/1ig1zh
reason: "Sidecar HTTP client implemented in PR #189 (net/http over Unix socket, POST /invoke)."
---



Replace binary framing client in sidecar with `net/http` over Unix socket. This task covers **non-streaming** (return-based) handlers only. SSE streaming is handled by 1ia4/1in0hv.

## What changes

### Remove binary framing

Delete `SendSocketData()` and `RecvSocketData()` from `client.go` (lines 52-86). These use `binary.BigEndian.PutUint32` / `io.ReadFull` with 4-byte length prefix. Replace with HTTP client.

### HTTP client setup

```go
client := &http.Client{
    Transport: &http.Transport{
        DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
            return net.Dial("unix", socketPath)
        },
    },
    Timeout: runtimeTimeout,  // default 5m, from ASYA_RUNTIME_TIMEOUT
}
```

One connection per message — no pooling. Clean state between invocations.

### Request format

```
POST http://localhost/invoke HTTP/1.1
Content-Type: application/json

{
  "id": "msg-uuid-001",
  "route": {"actors": ["a", "b", "c"], "current": 0},
  "headers": {"trace_id": "..."},
  "payload": {...}
}
```

**Note**: Uses CURRENT route format `{actors, current}` — NOT `{prev, curr, next}`. Route format migration is tracked separately in epic 1iah.

### Response parsing

**200 OK with JSON** — success (return-based handlers):

```json
{
  "frames": [
    {
      "type": "downstream",
      "route": {"actors": ["a", "b", "c"], "current": 1},
      "headers": {"trace_id": "..."},
      "payload": {"result": "..."}
    }
  ]
}
```

The response wraps frames in a `frames` array. For single-return handlers, the array has one element. For fan-out (handler returns a list), the array has multiple elements. Each frame contains the full routing context.

Map each frame to a `RuntimeResponse`:
- `frame.type` must be `"downstream"` (all frames in JSON response are downstream)
- `frame.route` → `RuntimeResponse.Route`
- `frame.headers` → preserved for downstream routing
- `frame.payload` → `RuntimeResponse.Payload`

### HTTP status code handling

| Status | Meaning | Sidecar action |
|---|---|---|
| `200` | Success (JSON body with frames) | Parse frames, return `[]RuntimeResponse` |
| `204` | Abort (handler returned None) | Return empty `[]RuntimeResponse` |
| `500` | Handler exception | Parse error JSON, return error `RuntimeResponse` |
| `503` | Runtime not ready (handler loading) | Retry with exponential backoff (see 1fbe/1ig1zh) |

**503 retry logic**:
- Backoff: 100ms, 200ms, 400ms, ... up to 5s cap
- Max retries: configurable (default: 30 — covers ~60s of handler loading)
- Log each retry at WARN level
- After max retries: treat as connection error → nack message for DLQ

**500 error response parsing**:

```json
{
  "error": "processing_error",
  "details": {
    "message": "Invalid input",
    "type": "ValueError",
    "traceback": "Traceback (most recent call last):..."
  }
}
```

Map to existing `RuntimeResponse` error fields:
- `Error` ← `error`
- `Details.Message` ← `details.message`
- `Details.Type` ← `details.type`
- `Details.Traceback` ← `details.traceback`

### Interface preservation

`CallRuntime()` signature and return type (`[]RuntimeResponse`) MUST remain unchanged. The router (`router.go`) calls this method and processes responses — no router changes should be needed.

### Connection error handling

- Socket not found → log error, return connection error (message will be nacked → DLQ)
- Connection refused → same as socket not found
- Timeout → send to x-sump with timeout error, crash pod (existing behavior)

## Key files

- `src/asya-sidecar/internal/runtime/client.go` — main changes
- `src/asya-sidecar/internal/runtime/client_test.go` — new HTTP-based tests
- `src/asya-sidecar/internal/runtime/types.go` — RuntimeResponse (no changes expected)

## Test plan

- Unit test: successful JSON response with single frame
- Unit test: successful JSON response with multiple frames (fan-out)
- Unit test: 204 No Content returns empty slice
- Unit test: 500 error response parsed correctly
- Unit test: 503 retry with eventual success
- Unit test: 503 max retries exhausted
- Unit test: connection refused handling
- Unit test: timeout handling
- Unit test: malformed JSON response

## References

- Epic design: 1fbe/epic.md (lines 57-179)
- Current binary client: `src/asya-sidecar/internal/runtime/client.go:52-142`
