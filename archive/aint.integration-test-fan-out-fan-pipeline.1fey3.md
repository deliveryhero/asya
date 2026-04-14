---
title: "Integration test: fan-out/fan-in pipeline"
status: merged
priority: 2
dependencies:
  - 1fci
  - 1i4x
  - 1isz
tags:
  - pr:211
---

## Summary

Integration tests for a complete fan-out/fan-in pipeline with multiple components: fan-out router -> sub-agents -> aggregator -> continuation actor. Tests the full message flow through the sidecar, runtime, and queue infrastructure.

The aggregator uses the v0 flavor (fanin-s3 with S3 split-key pattern). No sharding — single aggregator with S3 state proxy sidecar.

## Test Scenarios

1. **Homogeneous fan-out**: Fan-out router emits N slices to same sub-agent, all converge on aggregator, merged envelope reaches continuation actor
2. **Heterogeneous fan-out**: Fan-out router emits slices to different sub-agents, all converge on aggregator
3. **Fan-in suppression**: Verify partial messages reaching x-sink do NOT report to gateway (x-asya-fan-in header detection)
4. **Error handling**: Sub-agent failure -> slice reaches x-sump -> aggregator state cleaned up by TTL
5. **Header preservation**: Verify `x-asya-fan-in` headers survive through sub-agent processing
6. **Idempotency**: Duplicate message delivery -> slice is not written twice, completeness not double-triggered
7. **Concurrent arrivals**: Multiple slices arriving simultaneously -> all written to separate keys, exactly one emission

## Structure

```
testing/integration/fan-in/
+-- Makefile
+-- compose/
|   +-- tester.yml
|   +-- fan-out-router.yml
|   +-- sub-agents.yml
|   +-- aggregator.yml           # aggregator + S3 state proxy sidecar
+-- profiles/
|   +-- rabbitmq.yml
|   +-- sqs.yml
+-- tests/
|   +-- test_fanout_fanin_basic.py
|   +-- test_fanout_fanin_heterogeneous.py
|   +-- test_fanout_fanin_error.py
|   +-- test_fanout_fanin_sink_suppression.py
|   +-- test_fanout_fanin_idempotency.py
```

Note: Aggregator compose service includes MinIO (S3-compatible) as the state backend. The S3 state proxy sidecar connects to MinIO.

## Dependencies
- DEPENDS ON: Sidecar header preservation (1fci1o)
- DEPENDS ON: Aggregator crew actor (fanin-s3 flavor)
- DEPENDS ON: Sink non-reporting for x-asya-fan-in headers
- DEPENDS ON: State proxy sidecar (epic 1dmf) for S3 access

## References
- Fan-in RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md`


_Migrated from beads `asya-brq4`_
