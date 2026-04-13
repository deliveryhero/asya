---
title: Implement sidecar 410 Gone handling for task cancellation
status: merged
priority: 2
parent: emmc5
---

## Summary

Implement the sidecar-side handling of `410 Gone` responses from the gateway's
progress reporter. When the gateway returns `410 Gone` on `POST /mesh/{id}/progress`,
the sidecar must stop processing and persist the envelope to x-sink.

## Design (from rfc.md Section 7.5)

### Progress reporter response codes

| Response | Body | Sidecar action |
|----------|------|----------------|
| `200 OK` | `{"status": "running"}` | Continue processing normally |
| `410 Gone` | `{"status": "canceled"}` | Drop, persist to x-sink, don't route |
| `404 Not Found` | - | Task unknown - route to x-sump |
| `5xx` / timeout | - | Continue processing (fail-open) |

### Sidecar behavior on 410 Gone

1. **Before runtime call**: If `410` on initial "received" progress report:
   - Ack the message (prevent DLQ pollution)
   - Route to x-sink queue for S3 persistence (preserves envelope for audit)
   - Do NOT call the runtime
   - Log cancellation at INFO level

2. **After runtime call**: If `410` on "completed" progress report:
   - Ack the message
   - Route result to x-sink queue (preserves the work done)
   - Do NOT route to the next actor in the pipeline
   - Runtime's work is preserved, just not forwarded

3. **Fail-open on 5xx**: If gateway is unreachable, continue processing.

### Gateway side

`GET /mesh/{id}/status` (currently `GET /mesh/{id}/active`) needs to return:
- `200 OK` with `{"status": "running"}` for active tasks
- `410 Gone` with `{"status": "canceled"}` (or other terminal status) for inactive tasks

## Files to modify

- `src/asya-sidecar/internal/progress/reporter.go` - Handle 410 response
- `src/asya-sidecar/internal/router/router.go` - Conditional routing based on status
- `src/asya-gateway/internal/handlers/mesh.go` - Update status endpoint response
- Tests for both components
