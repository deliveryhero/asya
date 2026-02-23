---
title: Stateful Fan-In/Fan-Out
status: ideated
priority: 2 # medium
type: epic
---


## Summary
Implement dynamic fan-out and CDC-based fan-in for parallel sub-agent execution.

Enable list comprehension syntax in Flow DSL that compiles to parallel execution with result aggregation:
```python
p["results"] = [agent(p["items"][i]) for i in range(len(p["items"]))]
```

## Implementation Plan (by layer)

### Layer 1: Sidecar Infrastructure
- `asya-nduw` [P1] Preserve message headers through routing (CRITICAL)
- `asya-g69n` [P2] uuid4() for fan-out child message IDs
- `asya-2ozv` [P2] x-asya-route-override header resolution (depends on asya-nduw)
- `asya-9n0r` [P3] x-asya-root-id header for nested fan-out tracing (depends on asya-nduw)

### Layer 2: Sink/Sump Non-Reporting
- `asya-0bvg` [P2] Allow any status.phase in sink/sump; suppress gateway reporting (parent: asya-y4kr)

### Layer 3: Flow DSL Compiler
- `asya-pmor` [P2] Fan-out list comprehension and list literal parser
- `asya-q2kp` [P2] Fan-out router code generator (depends on asya-pmor)
- `asya-dulv` [P3] Fan-out/fan-in dot diagram visualization (depends on asya-pmor)

### Layer 4: Aggregator Crew Actor
- `asya-fi6u` [P2] Aggregator crew actor with RocksDB (depends on asya-0bvg)

### Layer 5: Testing
- `asya-8g3x` [P2] Component test: aggregator actor (depends on asya-fi6u)
- `asya-brq4` [P2] Integration test: fan-out/fan-in pipeline (depends on asya-nduw, asya-2ozv, asya-fi6u, asya-0bvg)
- `asya-1mqw` [P2] E2E test: compiled flow on Kind cluster (depends on asya-altb, asya-q2kp, asya-fi6u, asya-nduw, asya-2ozv, asya-0bvg)

### Infrastructure Dependencies (external)
- `asya-zpl` [P2] Research: stateful fan-in actor (blocked by asya-0bvg)

## Critical Path
```
asya-nduw (headers) → asya-2ozv (route-override) ─┐
                                                    ├─→ asya-brq4 (integration)
asya-0bvg (sink) → asya-fi6u (aggregator) ────────┘

asya-pmor (parser) → asya-q2kp (codegen) ──────┐
                                                ├──→ asya-1mqw (E2E)
asya-nduw + asya-2ozv + asya-fi6u + asya-0bvg ─┘
```
