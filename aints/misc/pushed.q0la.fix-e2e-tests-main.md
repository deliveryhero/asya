---
title: Fix e2e tests on main
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/misc/q0la.fix-e2e-tests-main
  - branch:misc/q0la.fix-e2e-tests-main
  - pr:274
---



## Investigation Summary

### Root Cause

The CI e2e tests (and all open PRs) fail because **actor sidecars enter CrashLoopBackOff
during cluster startup**, which delays task processing beyond the 120-second A2A streaming
timeout.

**Trigger**: PR #273 (`e15e9545`) split the single `asya-gateway` pod into separate
`asya-gateway-api` (A2A/MCP) and `asya-gateway-mesh` (actor callbacks) deployments.

**Bug**: The sidecar performs a mandatory one-shot health check on `ASYA_GATEWAY_URL`
at startup (`cmd/sidecar/main.go:245`). If the health check fails (10-second timeout,
no retries), the sidecar exits and Kubernetes restarts it with exponential backoff
(10s → 20s → 40s → …). When Helmfile deploys all components in parallel in CI,
actor pods (`x-sink`, `x-sump`, test actors) start before the mesh gateway service is
ready. The CrashLoopBackOff delays can easily exceed 1-2 minutes.

**Symptom observed**: During rolling upgrade locally, x-sink sidecar crashed with:
```
"Gateway health check failed - sidecar cannot start"
error="failed to reach gateway health endpoint: Get
  \"http://asya-gateway.asya-e2e.svc.cluster.local:8080/health\":
  dial tcp: lookup asya-gateway.asya-e2e.svc.cluster.local ...: no such host"
```

In CI (fresh deployment), the URL is correct (`asya-gateway-mesh...`) but the timing
causes the same CrashLoopBackOff pattern.

**Cascading effect**: A2A `message/stream` uses `waitAndRelayEvents()` which polls the
DB every 500ms for up to `skill.TimeoutSec` (120s for `test_echo`). If x-sink is in
CrashLoopBackOff for >120s after a task is submitted, the task times out and the SSE
stream returns the current status (typically `working` or timeout-state `failed`).

### Secondary Findings

1. **DB poll fix (ef61fb71) IS correct**: The `waitAndRelayEvents` 500ms DB poll works
   fine once x-sink is running. The poll correctly detects x-sink's `succeeded` update
   within 500ms.

2. **Injector timing race (local only)**: During rolling upgrade, pods created in the
   brief window before the new injector pod is ready get the OLD `ASYA_GATEWAY_URL`
   (`asya-gateway` instead of `asya-gateway-mesh`). Fixed by restarting those pods.
   This is a local artifact, not a CI issue.

3. **SQS queue backlog (local only)**: Old test-echo pod received SQS messages just
   before restart, couldn't ACK them before termination; messages became invisible for
   the visibility timeout (300-600s). New pod saw the queue as empty until visibility
   expired. Again, local artifact.

### Fix Applied

**File**: `src/asya-sidecar/cmd/sidecar/main.go`

Added `waitForGateway()` function that retries the health check every 5 seconds for up
to `ASYA_GATEWAY_READY_TIMEOUT` (default: 5 minutes). The sidecar now logs a warning
and retries instead of exiting immediately, eliminating CrashLoopBackOff when the mesh
gateway starts concurrently.

### Fix Status

- [x] `waitForGateway()` implemented in sidecar
- [x] Sidecar unit tests pass
- [ ] Build and deploy to local cluster for e2e verification
- [ ] Commit and push PR
