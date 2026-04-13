---
title: Fix flaky test_slow_actor_exceeds_sla SLA test in CI
status: open
priority: 3
parent: 00001
---

## Problem

`testing/e2e/tests/test_sla_e2e.py::test_slow_actor_exceeds_sla` fails
intermittently in CI with:

```
AssertionError: KEDA should rescale test-timeout pod after crash-on-timeout
```

The test asserts that KEDA rescales an actor after a timeout crash, but the
timing depends on message round-trip through sidecar+runtime chain and KEDA
polling interval. Under CI load, these timings are unreliable.

## Seen in

- PR #413 (e2e sqs-s3 run 24218853135)
- Previously documented as known flaky

## Fix ideas

- Increase timeout/polling window to accommodate CI load
- Use retry with backoff on the assertion instead of a single check
- Mark as `@pytest.mark.flaky(reruns=2)` as a stopgap
