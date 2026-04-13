---
title: "Component test: aggregator actor with RocksDB"
status: rejected
priority: 2
parent: 00000
dependencies:
  - 1fo5
reason: decided to go with virtual actors
---

## Summary

Component-level tests for the aggregator crew actor. Tests the aggregator in isolation with a real RocksDB instance inside Docker Compose.

## Test Scenarios

1. **Basic fan-in**: Send N+1 messages with matching `origin_id`, verify merged envelope is emitted
2. **Out-of-order arrival**: Send slices before parent payload (index 0), verify correctness
3. **Large fan-out**: Send 100+ slices, verify aggregation completes
4. **Multiple concurrent fan-ins**: Interleave messages from different `origin_id` groups, verify isolation
5. **Idempotent delivery**: Send same slice twice, verify no corruption
6. **State persistence**: Restart aggregator mid-aggregation, verify state survives (RocksDB on PVC)
7. **Aggregation key**: Verify JSON Pointer correctly places results in parent payload

## Structure

```
testing/component/aggregator/
├── Makefile
├── compose/
│   ├── tester.yml
│   └── aggregator.yml
├── profiles/
│   ├── rabbitmq.yml
│   └── sqs.yml
├── tests/
│   ├── test_aggregator_basic.py
│   ├── test_aggregator_persistence.py
│   └── test_aggregator_concurrent.py
```

## Dependencies
- DEPENDS ON: Aggregator crew actor (asya-fi6u)

## References
- RFC: docs/rfc/fan-in/rfc-fan-in.md (Aggregator Actor Design)


---
_Migrated from beads `asya-8g3x`_
