---
title: Stateful Fan-In/Fan-Out
priority: 2 # medium
type: epic
---


## Summary
Implement dynamic fan-out and fan-in for parallel sub-agent execution.

Enable list comprehension syntax in Flow DSL that compiles to parallel execution with result aggregation:
```python
p["results"] = [agent(p["items"][i]) for i in range(len(p["items"]))]
```

Fan-in uses a **split-key pattern on S3** via the state proxy sidecar (epic 1dmf). Each slice writes its own S3 object (zero contention), completeness is detected by listing, exactly-once emission uses atomic create-if-not-exists. No sharding, no CAS, no embedded databases. Aggregator handler is pluggable for future flavors (Redis CAS, sharded RocksDB).

## Implementation Plan (by layer)

### Layer 1: Sidecar Infrastructure
- `1fci1o` [P1] Preserve message headers through routing (CRITICAL)
- `1f0rar` [P2] uuid4() for fan-out child message IDs

### Layer 2: Sink/Sump Non-Reporting
- `1isz5r` [P2] Suppress gateway reporting for fan-in and fire-and-forget messages (depends on 1fci1o)
- (external, 1c46/1ffmnb) Allow any status.phase in sink/sump; only report terminal phases

### Layer 3: Flow DSL Compiler
- `1ih5oo` [P2] Fan-out list comprehension and list literal parser
- `1fr7i0` [P2] Fan-out router code generator (depends on 1ih5oo)
- `1froou` [P3] Fan-out/fan-in dot diagram visualization (depends on 1ih5oo)

### Layer 4: Aggregator Crew Actor
- `1i4xwg` [P2] Aggregator crew actor with S3 split-key pattern (depends on 1i9og1, state proxy epic 1dmf)

### Layer 5: Runtime Enhancement
- `1i9og1` [P2] Add `open(path, "x")` exclusive create mode to `asya_runtime.py`

### Layer 6: Testing
- `1feyz7` [P2] Integration test: fan-out/fan-in pipeline (depends on 1fci1o, 1i4xwg, 1isz5r)
- `1f0ehm` [P2] E2E test: compiled flow with fan-out/fan-in on Kind cluster (depends on 1fr7i0, 1fci1o, 1i4xwg, 1isz5r)

## Critical Path
```
1i9og1 (exclusive create) ─→ 1i4xwg (aggregator) ──┐
                                                     │
1fci1o (headers) ─→ 1isz5r (non-reporting) ─────────┼─→ 1feyz7 (integration)
                                                     │
1ih5oo (parser) ─→ 1fr7i0 (codegen) ────────────────┼─→ 1f0ehm (E2E)
                                                     │
1f0rar (uuid4) ─────────────────────────────────────┘
```
