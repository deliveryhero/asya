---
title: "E2E tests: full pipeline SLA and gateway backstop race"
status: pushed
priority: 2
assignee: Artem Yushkovskiy
parent: 34xba
tags:
  - worktree:.worktrees/timeout-handling/1kow.e2e-tests-full-pipeline-sla-gateway-backstop-race
  - branch:timeout-handling/1kow.e2e-tests-full-pipeline-sla-gateway-backstop-race
  - pr:272
---

## Scope

End-to-end tests in Kind cluster validating timeout behavior with real Crossplane-managed queues and full Kubernetes deployment.

## Test Cases

### Full pipeline with SLA
- Deploy 3-actor pipeline with XRD actorTimeout=10s
- Gateway sends task with timeout_seconds=30
- Pipeline completes in ~5s total
- Verify: task succeeds, deadline_at was set, all actors respected SLA

### Slow actor exceeds SLA
- Deploy pipeline with one slow actor (sleeps 15s)
- Gateway sends task with timeout_seconds=5
- Sidecar detects SLA expiry (or runtime times out with effective_timeout < 15s)
- Pod crashes (crash-on-timeout preserved)
- Task marked failed with reason=Timeout

### Gateway backstop race
- Deploy pipeline with actor scaled to 0 (KEDA minReplicas=0)
- Gateway sends task with timeout_seconds=3
- Message sits in queue while KEDA scales up (~10s)
- Gateway backstop fires at 3s, marks task failed
- Actor eventually processes stale message, sidecar reports timeout
- Gateway ignores sidecar report (task already terminal)

## Files
- `testing/e2e/tests/` (new test file or extend existing)

## Dependencies
- Depends on 1crv/1k8024 (integration tests should pass first)

## Wave
Wave 4: Cross-Component Validation
