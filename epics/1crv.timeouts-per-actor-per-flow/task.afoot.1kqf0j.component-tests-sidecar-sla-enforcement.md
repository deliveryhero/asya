---
title: Component tests for sidecar SLA enforcement
priority: 2 # medium
type: task
tags:
  - worktree:.worktrees/1crv/1kqf0j.component-tests-sidecar-sla-enforcement
  - branch:1crv/1kqf0j.component-tests-sidecar-sla-enforcement
  - pr:220
dependencies:
  - 1crv/1k1pjy
---




## Scope

Add component tests in Docker Compose validating sidecar SLA enforcement against a real transport (RabbitMQ/SQS).

## Test Cases

### Expired message
- Publish message with `status.deadline_at` in the past
- Sidecar receives, acks, routes to x-sink
- Runtime is never called (verify via runtime mock or call counter)
- x-sink receives message with `status.phase=failed, status.reason=Timeout`

### Tight SLA
- Publish message with `status.deadline_at` = now + 2s
- Actor has `ASYA_RESILIENCY_ACTOR_TIMEOUT=10s`
- Runtime is called with effective timeout of ~2s (not 10s)
- Verify via runtime mock that times out intentionally

## Files
- `testing/component/sidecar/` (new or extend existing test suite)

## Dependencies
- Depends on 1crv/1k1pjy (SLA enforcement must be implemented)

## Wave
Wave 2: Sidecar SLA Enforcement
