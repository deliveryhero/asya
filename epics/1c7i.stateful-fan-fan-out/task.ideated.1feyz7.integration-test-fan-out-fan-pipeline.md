---
title: "Integration test: fan-out/fan-in pipeline"
priority: 2 # medium
type: task
---



## Summary

Integration tests for a complete fan-out/fan-in pipeline with multiple components: fan-out router → sub-agents → aggregator → continuation actor. Tests the full message flow through the sidecar, runtime, and queue infrastructure.

## Test Scenarios

1. **Homogeneous fan-out**: Fan-out router emits N slices to same sub-agent, all converge on aggregator, merged envelope reaches continuation actor
2. **Heterogeneous fan-out**: Fan-out router emits slices to different sub-agents, all converge on same aggregator shard
3. **Route-override resolution**: Verify sidecar resolves `x-asya-route-override` header to route slices to correct aggregator shard
4. **Fan-in suppression**: Verify partial messages reaching x-sink do NOT report to gateway
5. **Error handling**: Sub-agent failure → slice reaches x-sump → aggregator TTL cleanup
6. **Header preservation**: Verify `x-asya-fan-in` and `x-asya-route-override` headers survive through sub-agent processing

## Structure

```
testing/integration/fan-in/
├── Makefile
├── compose/
│   ├── tester.yml
│   ├── fan-out-router.yml
│   ├── sub-agents.yml
│   └── aggregator.yml
├── profiles/
│   ├── rabbitmq.yml
│   └── sqs.yml
├── tests/
│   ├── test_fanout_fanin_basic.py
│   ├── test_fanout_fanin_heterogeneous.py
│   ├── test_fanout_fanin_error.py
│   └── test_fanout_fanin_sink_suppression.py
```

## Dependencies
- DEPENDS ON: Sidecar header preservation (asya-nduw)
- DEPENDS ON: Sidecar route-override resolution (asya-2ozv)
- DEPENDS ON: Aggregator crew actor (asya-fi6u)
- DEPENDS ON: asya-0bvg (sink non-reporting)

## References
- RFC: docs/rfc/fan-in/rfc-fan-in.md


---
_Migrated from beads `asya-brq4`_
