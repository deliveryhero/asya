---
title: "Un-xfail fan-out/fan-in E2E tests: add spec.stateProxy to aggregator and migrate VFS reads to ABI"
priority: 2 # medium
type: task
tags:
  - worktree:.worktrees/1l01/1pjo6p.un-xfail-fan-out-fan-in-e2e-tests
  - branch:1l01/1pjo6p.un-xfail-fan-out-fan-in-e2e-tests
---

5 tests in `testing/e2e/tests/test_fanout_fanin_flow_e2e.py` are xfailed with:
`"Fan-out/fan-in flow requires VFS-based route modification and S3 state-proxy (not yet functional in E2E)"`

Two blockers remain:

1. `research-flow-aggregator.yaml` sets `ASYA_STATE_PROXY_MOUNTS` env var but lacks
   `spec.stateProxy` on the AsyncActor CRD. Without it, the injector never injects the
   state proxy sidecar. Need to add `spec.stateProxy` with connector image and mount config.

2. The aggregator handler (`asya_crew.fanin.s3_split_key.aggregator`) reads message
   metadata via VFS (`/proc/asya/msg/`), but VFS was removed in favor of the ABI yield
   protocol. The handler needs migrating to use `yield "GET", ".headers.x-asya-fan-in"`
   instead of file I/O.

Tests to un-xfail after fix:
- `test_fanout_fanin_basic_3_topics`
- `test_fanout_fanin_no_false_positives_from_partial_slices`
- `test_fanout_fanin_10_topics`
- `test_fanout_fanin_single_topic`
- `test_fanout_fanin_concurrent_requests`
- `test_fanout_fanin_aggregator_restart_mid_aggregation`

----
2026-03-02:
Skipped tests — breakdown by blocker

  ┌──────────────────────────┬─────────────────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────┐
  │         Blocker          │                              Tests                              │                                   What's needed                                   │
  ├──────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ State-proxy not deployed │ 9 tests (s3_persistence ×3, state_persistence ×2,               │ x-sink/x-sump need the state-proxy sidecar connector to persist results to S3.    │
  │  in E2E                  │ error_handling ×1, fanout_fanin ×3... wait, actually fanout is  │ Without it, crew actors can't read/write S3. Aint 1l01/1pjo6p is actively working │
  │                          │ different)                                                      │  on this. NOTE: also need to deploy new GCS state-proxies                     │
  ├──────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ VFS-based route          │ 11 tests (flow_nested_if ×5, fanout_fanin ×6)                   │ Flow routers use ABI yield "SET", ".route.next", [...] which requires the VFS     │
  │ modification             │                                                                 │ protocol to be functional in E2E. Same aint 1l01/1pjo6p. NOTE: we replaced VFS with ABI!! │
  ├──────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Crossplane missing       │ 6 tests (dlq ×2, queue_health ×4)                               │ Crossplane composition doesn't configure SQS RedrivePolicy or DLQ yet. Separate   │
  │ DLQ/RedrivePolicy        │                                                                 │ feature work needed.  -> same needed for PubSub!!                                 │
  ├──────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ XRD missing timeout      │ 1 test (timeout_crash)                                          │ AsyncActor XRD doesn't expose timeout in spec yet.                                │
  │ field                    │                                                                 │                                                                                   │
  ├──────────────────────────┼─────────────────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
  │ Test environment         │ 2 tests (gateway_restart, full_cluster_restart)                 │ Timing-sensitive — pod restart + task completion race. Not a feature gap, just    │
  │ flakiness                │                                                                 │ test robustness.                                                                  │
  └──────────────────────────┴─────────────────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────┘

  The two biggest blockers are state-proxy (9 tests) and VFS route modification (11 tests) — both gated on the same aint (1l01/1pjo6p — un-xfail fan-out/fan-in). Once state-proxy is
  deployed in E2E, 20 of the 32 skipped tests should be unblockable.
