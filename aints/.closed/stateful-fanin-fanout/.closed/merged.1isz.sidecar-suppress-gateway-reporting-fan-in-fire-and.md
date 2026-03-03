---
title: "Sidecar: suppress gateway reporting for fan-in and fire-and-forget messages"
priority: 2 # medium
dependencies:
  - 1fci
---


## Summary

Add two non-reporting mechanisms to the sidecar's progress reporter so that partial fan-in results and fire-and-forget yield children do NOT trigger false "finished" status reports to the gateway.

Currently, when the aggregator returns `None` (still accumulating), the sidecar acks the message and routes it to x-sink with `status.phase = "succeeded"`. Without suppression, x-sink's progress reporter would report a false "finished" to the gateway.

## Mechanisms (from RFC)

### 1. `x-asya-fan-in` header detection
- **When**: Message has `x-asya-fan-in` header -- it's a partial fan-in result
- **Action**: Ack and consume. Do NOT report to gateway.
- **Why checked first**: Fan-in index 0 (parent payload) has NO `parent_id` but must still be suppressed. The `x-asya-fan-in` header is the only reliable signal.

### 2. `parent_id` detection (fire-and-forget yield children)
- **When**: Message has `parent_id` set and NO `x-asya-fan-in` header -- it's a fire-and-forget yield child
- **Action**: Ack and consume. Do NOT report to gateway.
- **Rationale**: Only the first yield (index 0, keeps original `message.id`) is tracked by the gateway. Subsequent yields are side effects.

## Changes

### `src/asya-sidecar/internal/progress/reporter.go`
- Before reporting to gateway, check for `x-asya-fan-in` in message headers -> skip reporting
- Before reporting to gateway, check for `parent_id` on message (and no `x-asya-fan-in`) -> skip reporting
- Order: check mechanism 1 first, then mechanism 2, then existing reporting logic

### Tests
- Message with `x-asya-fan-in` header reaching x-sink -> no gateway report
- Message with `x-asya-fan-in` header reaching x-sump -> no gateway report
- Message with `parent_id` (no fan-in header) reaching x-sink -> no gateway report
- Message with `parent_id` (no fan-in header) reaching x-sump -> no gateway report
- Normal message (no fan-in, no parent_id) -> gateway report as usual
- Fan-in index 0 (has fan-in header, NO parent_id) -> no gateway report

## Dependencies
- DEPENDS ON: 1fci1o (headers must survive routing first)

## References
- RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (Non-Reporting Mechanisms in x-sink and x-sump)
