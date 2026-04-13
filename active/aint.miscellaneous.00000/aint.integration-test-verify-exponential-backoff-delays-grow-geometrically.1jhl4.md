---
title: "Integration test: verify exponential backoff delays grow geometrically"
status: open
priority: 3
parent: 00000
---

## Context

PR #193 added `test_retry_created_at_preserved` which verifies attempt counts and timestamps
exist, but does NOT verify that delay intervals actually grow geometrically between retries.

This was deferred because SQS visibility timeout has ~1s granularity, making sub-second timing
assertions flaky.

## What to do

Add a new test in `testing/integration/sidecar-runtime/tests/test_retry.py` that:

1. Publishes a message to `test-retry-fail` (always fails, max 3 attempts).
2. Waits for the message to arrive at `x-sump`.
3. Reads `status.updated_at` across the 3 attempts by inspecting intermediate state — or
   alternatively, measures wall-clock time between publish and sump arrival.

**Feasible approach** (avoid per-attempt timestamps which require middleware):
- Use two messages with different retry intervals (one constant 1s, one exponential starting 1s).
- Measure total wall-clock time for each to exhaust 3 attempts.
- Assert exponential total time >= 1.5x constant total time (loose ratio to tolerate SQS jitter).

**Pre-condition**: requires a second `test-retry-fail-exp` actor with
`ASYA_RESILIENCY_RETRY_POLICY=exponential` and `ASYA_RESILIENCY_RETRY_BACKOFF_COEFFICIENT=2`.

## Files

- `testing/integration/sidecar-runtime/tests/test_retry.py`
- `testing/integration/sidecar-runtime/compose/actors.yml` (new actor)
- `testing/integration/sidecar-runtime/configs/sqs-queues.txt` (new queue)
- `testing/shared/compose/configs/rabbitmq-definitions.json` (new queue def)
