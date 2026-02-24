---
title: Allow any status.phase in sink/sump; only report terminal phases to gateway
priority: 2 # medium
type: task
tags:
  - type:feature
  - worktree:.worktrees/1c46/1ffmnb.allow-any-status-phase-sink-sump-only-report
  - branch:1c46/1ffmnb.allow-any-status-phase-sink-sump-only-report
---






## Context

Currently, `x-sink` (sink.py) validates that `status.phase` is exactly `"succeeded"` or `"failed"` and always reports final state to the gateway. `x-sump` (sump.py) uses phase only for logging level decisions and always terminates the message.

This is too restrictive for upcoming patterns:

- **Fan-in**: A partial message arriving at x-sink while waiting for sibling parts to arrive in parallel should NOT be reported as "succeeded" to the HTTP gateway. It needs a non-terminal phase (e.g. `"waiting"`, `"partial"`) so the gateway knows the overall request is not yet complete.
- **Human-in-the-loop**: A message may be "frozen" with a custom phase (e.g. `"awaiting_approval"`) — it should be consumed/acked but not reported as final to the gateway.

## Required Changes

### 1. `src/asya-crew/asya_crew/sink.py`
- Remove the strict validation that only allows `"succeeded"` / `"failed"` in `status.phase`
- Allow ANY string value in `status.phase`
- Implement three non-reporting mechanisms (checked in this order):
  1. **`x-asya-fan-in` header**: Fan-in partial → ack, persist S3, run hooks, do NOT report to gateway
  2. **`parent_id` set** (no fan-in header): Fire-and-forget yield child → ack, persist S3, run hooks only if `ASYA_SINK_FANOUT_HOOKS=true` (default: `false`), do NOT report to gateway
  3. **Non-terminal `status.phase`**: phase not in `{"succeeded", "failed"}` → ack, persist S3, run hooks, do NOT report to gateway
- If none of the above: normal terminal processing (persist, hooks, report to gateway)

### 2. New env var: `ASYA_SINK_FANOUT_HOOKS`
- Optional, default `false`
- Controls whether registered finalizer hooks run for fire-and-forget fan-out children (messages with `parent_id` set)
- Disabled by default: fan-out can produce many children, hooks (Slack notifications, webhook calls) would fire per child
- Set to `true` for audit/observability use cases

### 3. `src/asya-crew/asya_crew/sump.py`
- Allow ANY string value in `status.phase` (currently defaults to `"unknown"` if missing)
- Same three non-reporting mechanisms as sink
- Adjust logging: log non-terminal phases at INFO level (not ERROR, not DEBUG)

### 4. `src/asya-sidecar/internal/router/router.go`
- Verify that when a message has remaining actors to visit, the sidecar sets `status.phase = "processing"` before forwarding. Already confirmed correct via `ensureAndUpdateStatus()`.
- (Future follow-up) Preserve custom `status.phase` from runtime responses when routing to x-sink

### 5. Tests
- Unit tests for sink.py with non-terminal phases
- Unit tests for sink.py with `x-asya-fan-in` header
- Unit tests for sink.py with `parent_id` set (fire-and-forget)
- Unit tests for `ASYA_SINK_FANOUT_HOOKS` env var (true/false)
- Unit tests for sump.py with non-terminal phases
- Verify gateway is NOT called for non-terminal phases
- Verify S3 persistence still works for all cases
- Verify existing behavior unchanged for normal `"succeeded"` / `"failed"`

## Use Cases Enabled

1. **Fan-in aggregation**: Router sends partial results to x-sink with `x-asya-fan-in` header. Sink acks, persists, runs hooks, but does NOT tell gateway "succeeded".

2. **Fire-and-forget fan-out**: Yield children with `parent_id` set reach x-sink. Sink acks, persists, optionally runs hooks (configurable), does NOT report to gateway.

3. **Human-in-the-loop**: Router sends message to x-sink with `phase="awaiting_approval"`. Sink acks, persists, runs hooks. An external system later approves and re-injects with `phase="succeeded"`.


---
## Notes

## Dependency Rationale

- **Blocks asya-7qh** (Epic: Stateful Fan-In/Fan-Out): Fan-out produces N partial messages that arrive at x-sink. Without this bead, x-sink would reject or incorrectly report them as terminal to the gateway.
- **Blocks asya-9lhh** (Gateway: status.phase reporting): Gateway needs to understand that non-terminal phases should NOT trigger final result reporting.
- **Blocks asya-zpl** (Research: Stateful fan-in actor): The fan-in aggregator will send partial results to x-sink with custom phases.
- **Child of asya-y4kr** (Epic: Error Handling): Extends the status.phase lifecycle with support for arbitrary non-terminal phases.

## Three Non-Reporting Mechanisms in Sink/Sump

This bead implements mechanism 3 (phase-based). Mechanisms 1 and 2 are separate but should be implemented together.

### 1. `x-asya-fan-in` header (fan-in RFC)
- Fan-in partial → ack silently, no S3, no gateway
- Checked first: fan-in index 0 has no `parent_id` but must still suppress

### 2. `parent_id` set (fire-and-forget yield fan-out)
- Yield-only fan-out is fire-and-forget: only the first message (index 0, keeps original message.id) is tracked by the gateway
- Subsequent yields (index > 0, parent_id set) → ack, persist S3, no gateway report
- Signal: `parent_id` present AND no `x-asya-fan-in` header

### 3. Non-terminal `status.phase` (THIS bead)
- phase not in {"succeeded", "failed"} → ack, persist S3, no gateway report
- For human-in-the-loop ("awaiting_approval"), future custom states
- Prerequisite: sidecar must stop overwriting custom phases from runtime responses

## Sidecar Phase Analysis (2026-02-15)

Verified sidecar phase transitions are correct for normal flow:
- `ensureAndUpdateStatus()`: phase="processing" before runtime call
- `routeResponse()`: phase="pending" when forwarding to next actor
- `routeResponse()`: phase="succeeded" only when route exhausted
- `sendToSinkQueue()`: phase="succeeded" when runtime returns None

## parent_id Preservation

parent_id is NOT preserved through non-fan-out actors (routeResponse constructs fresh Message). For nested fan-outs need `root_id = root_id or parent_id` (x-asya-root-id header). Separate bead needed.

See also: docs/rfc/rfc-actor-states.md


---
_Migrated from beads `asya-0bvg`_
