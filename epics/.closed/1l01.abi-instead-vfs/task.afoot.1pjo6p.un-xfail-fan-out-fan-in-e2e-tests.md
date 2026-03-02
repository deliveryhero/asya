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
