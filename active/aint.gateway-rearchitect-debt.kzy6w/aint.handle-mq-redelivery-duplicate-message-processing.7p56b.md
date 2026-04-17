---
title: Handle MQ redelivery duplicate message processing
status: open
priority: 3 # low
tags: [gateway-rearchitect, resiliency]
---

## Problem

When an MQ visibility timeout expires before the actor finishes processing,
the message becomes visible again and a second pod picks it up. Two pods now
process the same envelope concurrently.

**Current mitigations** (from gateway-rearchitect/63keu):
- **Monotonic status ordering** in mesh-api: `statusOrder[new] >= statusOrder[current]`.
  Terminal statuses (succeeded/failed/canceled = order 3) can never be overwritten.
  Duplicate "running" updates are idempotent (same order value).
- **Sidecar pre-flight check**: `GET /api/v1/mesh/{id}` before processing.
  If status is already terminal, skip processing. But this has a TOCTOU window
  (status can change between check and processing start).
- **Conditional writes**: `PUT /keys/{key}?if_status=X` in state-proxy-pg
  ensures atomic status transitions. But both pods pass the check if they
  read the same pre-transition status.

**What's NOT mitigated**:
- Duplicate actor execution (wasted compute: GPU time, API calls, etc.)
- Duplicate side effects (if actor writes to external systems)
- Two envelopes dispatched to the next actor queue (fan-out of one becomes two)

## Scenarios

1. **Slow actor**: Actor takes 5 min, SQS visibility timeout is 5 min.
   Timeout expires, message redelivered. Second pod starts processing.
   Both finish, both dispatch to next actor. Next actor processes twice.

2. **Pod eviction**: Pod A processing, gets evicted (spot instance, OOM).
   Message redelivered to Pod B. Pod A's work is lost (no side effects).
   This is the CORRECT behavior — not a bug, just normal retry.

3. **Network partition**: Pod A finishes but can't ack the message (network
   issue to MQ). Message redelivered. Pod B processes again. Duplicate.

## Potential Solutions

### Option A: Distributed lock (Redis/DynamoDB)
- Before processing, acquire lock: `SET msg:{id}:lock {pod_id} NX EX 300`
- If lock exists, skip processing (another pod has it)
- Pros: prevents duplicate execution
- Cons: adds Redis dependency, lock expiry edge cases, complexity

### Option B: Idempotency key in envelope
- Envelope carries `attempt_id` (unique per delivery attempt)
- Mesh-api rejects duplicate `attempt_id` writes
- Pros: no external dependency, deterministic
- Cons: MQ must provide unique delivery ID (SQS has MessageId + ReceiptHandle,
  RabbitMQ has delivery tag)

### Option C: Optimistic check before dispatch
- Before dispatching to next actor queue, sidecar checks mesh-api status
- If already terminal (another pod finished first), skip dispatch
- Pros: simple, no new infrastructure
- Cons: TOCTOU window (small but exists), doesn't prevent duplicate execution

### Option D: Increase visibility timeout
- Set visibility timeout >> expected processing time
- Reduces redelivery probability to near zero
- Pros: simplest, no code change
- Cons: increases recovery time when a pod actually crashes

## Recommendation

**Option D (increase timeout) for v1. Option C (check before dispatch) as
belt-and-suspenders. Option A/B for v2 if duplicates are observed in production.**

Most Asya workloads are ML training (minutes to hours). Setting visibility
timeout to 2x expected duration eliminates 99% of redelivery. The remaining
edge cases (pod crash, network partition) are handled by the existing monotonic
status ordering.

## Related

- Gateway rearchitect RFC: `.aint/active/aint.gateway-rearchitect.63keu/rfc.md`
- RFC addendum section 5 (MQ redelivery)
- Monotonic status ordering: `internal/mesh/events.go` (StatusAdvances)
- Pre-flight check: `internal/router/router.go` (CheckMessage)
