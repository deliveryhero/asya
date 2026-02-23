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
- (external) Allow any status.phase in sink/sump; suppress gateway reporting

### Layer 3: Flow DSL Compiler
- (external) Fan-out list comprehension and list literal parser
- `1fr7i0` [P2] Fan-out router code generator (simplified: no sharding by default)
- `1froou` [P3] Fan-out/fan-in dot diagram visualization

### Layer 4: Aggregator Crew Actor
- [P2] Aggregator crew actor with S3 split-key pattern (depends on state proxy, epic 1dmf)

### Layer 5: Runtime Enhancement
- [P2] Add `open(path, "x")` exclusive create mode to `asya_runtime.py`

### Layer 6: Testing
- [P2] Integration test: fan-out/fan-in pipeline
- `1f0ehm` [P2] E2E test: compiled flow with fan-out/fan-in on Kind cluster

## Critical Path
```
1fci1o (headers) ──────────────────────────┐
                                            ├─→ integration test
sink non-reporting → aggregator (S3) ──────┘

parser → 1fr7i0 (codegen, simplified) ────┐
                                           ├──→ 1f0ehm (E2E)
1fci1o + aggregator + sink ───────────────┘
```
now 