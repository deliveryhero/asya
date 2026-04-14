---
title: "Stealth mode: x-asya-mesh-status header to disable gateway task tracking"
status: merged
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - pr:284
---


## Problem

When messages are sent directly to actor queues (bypassing the gateway), the sidecar still attempts to report to `/mesh/{id}/*` endpoints. Currently this is partially tolerated:
- `/mesh/{id}/progress` silently accepts unknown task IDs (200 OK)
- `/mesh/{id}/active` treats "not found" as "inactive" — could abort processing
- `/mesh/{id}/final` tries to finalize a non-existent task
- `/mesh/{id}/fly` events go nowhere

## Solution

Add `x-asya-mesh-status: off` envelope header that disables all gateway mesh reporting by the sidecar.

### Why not empty ID?
ID is already overloaded (correlation, logging, fan-out parent/child linking, DLQ tracing). Making "empty = stealth" breaks fan-out and removes log correlation.

### Why not auto-create on first progress?
Stealth mode should be explicit opt-in, not implicit. Needed for testing and lab workflows.

### Naming rationale
- `x-asya-no-track` sounds like telemetry opt-out (OTEL traces/metrics)
- `x-asya-mesh` alone is ambiguous — actors communicating is also "mesh"
- `x-asya-mesh-status` clearly names the subsystem: the gateway's task status tracking layer (`/mesh/{id}/progress`, `/mesh/{id}/final`, etc.)

## Implementation

Single gate function in the sidecar router:

```go
func (r *Router) isMeshStatusEnabled(msg *envelopes.Envelope) bool {
    if r.progressReporter == nil {
        return false
    }
    if v, ok := msg.Headers["x-asya-mesh-status"]; ok && v == "off" {
        return false
    }
    return msg.ID != ""
}
```

All four mesh calls gate on this: `ReportProgress`, `ForwardFly`, `ReportFinalError`, `CheckActive`.

Fan-out in stealth mode works: ID preserved for correlation, child envelopes inherit the header, sidecars skip all `/mesh/` calls.
