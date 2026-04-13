---
title: Fix flaky SLA integration test (sidecar-runtime rabbitmq)
status: merged
priority: 2
assignee: Claude
parent: 00000
tags:
  - pr:263
---

## Problem

`test_sla.py::TestSLAEffectiveTimeout::test_sla_constrains_effective_timeout`
fails intermittently on CI in the `sidecar-runtime (rabbitmq)` integration test.

The test sets a 5s SLA deadline and polls x-sump for 15s, expecting the message
to appear within that window. Under CI load, the processing chain (publish →
sidecar consume → runtime timeout → sidecar route to x-sump → test consume)
occasionally exceeds 15s.

## Failed CI run

https://github.com/deliveryhero/asya/actions/runs/22688336948/job/65777147695

## Error

```
AssertionError: No message in x-sump after 15s.
effectiveTimeout should be ~5s (SLA), not 30s (ACTOR_TIMEOUT).
assert None is not None
```

## Fix approach

Increase the poll timeout or make the test more resilient to CI latency.
