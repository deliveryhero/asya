---
title: Fix e2e tests on main
status: merged
priority: 2
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/misc/q0la.fix-e2e-tests-main
  - branch:misc/q0la.fix-e2e-tests-main
  - pr:274
---

## Summary

Two independent root causes fixed. PR #274.

## Root Cause 1: Sidecar CrashLoopBackOff

**File**: `src/asya-sidecar/cmd/sidecar/main.go`

Sidecar performed a mandatory one-shot health check on `ASYA_GATEWAY_URL` at
startup (10s timeout, no retries). In CI, Helmfile deploys all components in
parallel — actor pods start before the mesh gateway service is ready. Health
check fails → sidecar exits → Kubernetes restarts with exponential backoff (10s
→ 20s → 40s ...). CrashLoopBackOff delays of 1-2 minutes cause all tasks to
time out before processing completes.

**Fix**: `waitForGateway()` retries every 5s for up to `ASYA_GATEWAY_READY_TIMEOUT`
(default 5 min). Sidecar logs warning and retries instead of exiting.

## Root Cause 2: StoreAdapter Feedback Loop

**File**: `src/asya-gateway/internal/a2a/blocking.go`

`waitAndRelayEvents` forwarded ALL subscription updates (including non-terminal
`pending`) to `eq.Write()`. This created a ~100×/second feedback loop:

```
eq.Write(submitted) → StoreAdapter.Save() → internal.Update(pending)
  → notifyListeners(pending) → ch receives pending → eq.Write(submitted)
```

The loop overwrote `tasks.status` back to `pending` within 10ms of any update,
including the mesh gateway's `succeeded` write. The 500ms DB poll never detected
terminal state. Task only resolved after 120s timeout timer returned `failed`.

**Evidence**: 11,923 `pending` rows written to `task_updates` per task after the
mesh gateway wrote `succeeded`.

**Fix**: Drop non-terminal subscription updates. Subscription channel is now only
a fast-path for in-process terminal state detection (e.g., timeout timer).
Cross-process terminal state (mesh gateway writes) detected by 500ms DB poll.

## Additional Issues Found

3. **Local registry TLS cert expired** (CI only affects fresh cluster): The Kind
   cluster's local Docker registry (`172.22.0.x:5000`) used for `function-asya-overlays`
   had an expired TLS cert. Fixed by adding `skip_verify = true` to containerd config.

4. **Port 8081 not mapped in existing cluster**: The `kind-config.yaml` was updated
   to add `hostPort: 8081 → containerPort: 30081` for the mesh gateway split, but
   the existing local cluster was created before this change. CI creates clusters
   fresh from `kind-config.yaml` so CI is not affected. Workaround for local: use
   `http://172.22.0.2:30081` directly (NodePort), or recreate the cluster.

## Fix Status

- [x] `waitForGateway()` implemented in sidecar (Fix 1)
- [x] StoreAdapter feedback loop broken in gateway (Fix 2)
- [x] Unit tests pass: `make test-unit` in gateway and sidecar
- [x] E2E streaming test passes: was 120s timeout→failed, now 2.5s→completed
- [x] Full e2e suite: 124 passed (6 failures are local cluster infrastructure only, not in CI)
- [x] PR #274 created and pushed

