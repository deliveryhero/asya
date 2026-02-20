---
title: Design Flow deployment as unified entity
status: done
priority: 2 # medium
type: task
tags:
  - type:feature
---




## Background

Flows are a unified series of actors generated from `flow.py` by `asya flow compile` (see `examples/flows/`). They have:
- **Entrypoint**: Where messages enter the flow
- **Exitpoint**: Where processed messages exit
- **Branching/loops**: Python-like control flow (if-else, conditionals)
- **Composability**: Flows can include other flows

Flows can represent various constructs:
- Specific functionality with branching logic
- AI agents or sub-agents
- MCP tools
- Reusable pipeline components

## Current Approach (Labels)

Use Kubernetes labels on AsyncActor CRDs:
```yaml
metadata:
  labels:
    asya.sh/flow: flow-name
    # or multi-flow membership:
    # asya.sh/flows: '["flow-1","flow-2"]'
```

**Pros**:
- Simple, no new CRD required
- Works with existing kubectl: `kubectl get asyncactors -l asya.sh/flow=flow-name`
- Native K8s label selectors
- Minimal operator changes

**Cons**:
- No lifecycle management (flow as a unit)
- No validation of flow structure (entrypoint exists, exitpoint valid)
- No single source of truth for flow topology
- Label value limits (63 chars, no special chars)

## Alternative: Flow CRD

Define a new `Flow` CRD that references constituent actors:
```yaml
apiVersion: asya.dev/v1alpha1
kind: Flow
metadata:
  name: order-processing
spec:
  entrypoint: validate-order
  exitpoint: payment-processor
  actors:
    - validate-order
    - express-handler
    - standard-handler
    - payment-processor
  # Optional: flow composition
  includes:
    - name: payment-flow
      entrypoint: payment-processor
```

**Pros**:
- Single resource describes entire flow
- Lifecycle management (create/delete flow as unit)
- Validation (entrypoint exists, actors exist, topology valid)
- Clear ownership model
- Could auto-generate labels on referenced actors

**Cons**:
- New CRD to maintain
- Potential sync issues between Flow and actors
- More complex operator logic

## Research Questions

1. **Label vs CRD**: Which approach better serves operational needs?
2. **Lifecycle**: Should flows have independent lifecycle or just be a view?
3. **Composition**: How to handle nested flows (flow including flow)?
4. **Telemetry**: How to propagate flow context through OTEL spans?
5. **UI Integration**: What does asya-stagedoor need to render flows?
6. **Compiler Output**: Should `asya flow compile` generate Flow CRD or just labels?

## Deliverables

1. **Research document**: Alternatives analysis with recommendations
2. **Design document**: Implementation plan for chosen approach
3. **OTEL design**: How flow context propagates through tracing
4. **Migration path**: How to evolve from MVP to full implementation


---
**Close reason**: Decision made: Labels + CLI approach (not CRD). 1:M actor-flow with asya.sh/flow label. CLI manages lifecycle via asya flow deploy/undeploy. See asya-qyzk closure for full rationale.


---
_Migrated from beads `asya-5av`_
