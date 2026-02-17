---
title: "Research: A/B, canary, blue/green routing strategies for Asya"
status: open
priority: 2 # medium
type: task
tags:
  - type:feature
---


## Research Objective

Explore how Asya can support progressive deployment and traffic routing strategies:
- **A/B testing** - Route percentage of traffic to variant actors
- **A/B/n testing** - Multiple variants with configurable splits
- **Multi-armed bandit** - Dynamic traffic allocation based on performance metrics
- **Canary deployments** - Gradual rollout with automatic rollback
- **Blue/green deployments** - Zero-downtime switching between versions

## Core Challenge

Asya uses **envelope-based message routing** at the framework level, not HTTP-level routing. Standard tools (Istio, Nginx, Linkerd) route based on HTTP headers/paths, but Asya routes via:
- Queue names in `route.actors` array
- Message headers in envelope `headers` field
- Sidecar → Queue routing logic

This means we need **message-level routing** rather than request-level routing.

## Key Research Questions

### 1. Where should routing decisions happen?

**Option A: Gateway-level (entry point)**
- Gateway adds routing headers based on experiment config
- Pro: Centralized, easy to audit
- Con: Couples gateway to experiment logic

**Option B: Dedicated router actors (Flow DSL)**
- Router actors read experiment config, modify routes
- Pro: Composable, fits Flow DSL model
- Con: Requires router in every flow

**Option C: Sidecar-level (transparent)**
- Sidecar reads headers, routes to versioned queues
- Pro: Transparent to user code
- Con: Complex sidecar logic, queue proliferation

**Option D: Operator-level (K8s native)**
- Operator creates versioned deployments, manages traffic split
- Pro: K8s native, integrates with GitOps
- Con: Coarse-grained (actor-level, not message-level)

**Option E: Actor-level interceptor routers**
- Intercept calls to logical actor (e.g., `model`) via a router actor
- Router rewrites route to point to versioned actors (`model-a`, `model-b`)
- Pro: No framework changes, works today, full user control
- Pro: Users can implement custom MAB algorithms in Python
- Con: Extra hop latency, user manages experiment config
- Example: `gateway → preprocess → model-router → model-a/model-b → postprocess`

### 2. Header schema for routing flags

Should envelope headers include:
```json
{
  "headers": {
    "x-asya-experiment": "pricing-v2",
    "x-asya-variant": "treatment-b",
    "x-asya-sticky-session": "user-12345"
  }
}
```

Questions:
- Should user handlers have read access to variant headers?
- Should user handlers be able to SET variant headers (override)?
- How to ensure consistency across a pipeline (sticky sessions)?

### 3. Queue versioning strategy

How to name versioned actor queues?
- `asya-prod-text-analyzer` (current)
- `asya-prod-text-analyzer-v2` (canary)
- `asya-prod-text-analyzer-canary` (pattern)

Who creates/manages versioned queues?

### 4. GitOps integration

**Flux + Flagger**
- Flagger supports canary/blue-green for Deployments
- How does this work with KEDA ScaledObjects?
- Can Flagger manage AsyncActor CRDs?
- Flagger uses Istio/Linkerd for traffic shifting - not applicable to message routing

**ArgoCD + Argo Rollouts**
- Argo Rollouts has Analysis for metric-based decisions
- Rollouts manages Deployment replicas
- Same question: how to shift MESSAGE traffic, not HTTP traffic?

### 5. Metrics and observability

For canary/MAB to work, we need:
- Per-variant success/error rates
- Per-variant latency metrics
- Automatic rollback triggers

Where do these metrics come from?
- Sidecar reports to progress reporter
- Gateway tracks envelope completion
- Need variant-aware metrics labels

## Research Deliverables

1. **Architecture decision record** for chosen approach
2. **PoC implementation** of simplest viable option
3. **Integration path** with Flux/Flagger or Argo Rollouts
4. **Flow DSL extensions** if router-based approach chosen

## Related Concepts

- Envelope protocol (docs/architecture/protocols/)
- Flow DSL compiler (src/asya-cli/asya_cli/commands/flow/)
- Progress reporter (src/asya-sidecar/internal/progress/)
- KEDA integration (src/asya-operator/)


---
## Notes

## Initial Thoughts (from creation)

**User handler access to routing flags:**
- Handlers probably SHOULD have READ access (for logging, variant-specific logic)
- Handlers probably SHOULD NOT have WRITE access (breaks experiment integrity)
- Runtime could strip/protect certain headers

**Flow DSL router consideration:**
- Flow DSL already generates routers for conditionals
- Natural fit: add `experiment()` primitive to Flow DSL
- Example: `p = experiment("pricing", [v1_handler, v2_handler], weights=[90, 10])`

**Queue vs header routing:**
- Queue-based: simpler, but queue explosion (N actors × M versions)
- Header-based: single queue, sidecar routes to versioned pods
- Hybrid: use headers for experiment ID, queue suffix for major versions

**GitOps challenge:**
- Flagger/Rollouts work at HTTP level (Istio VirtualService, etc.)
- We need a "message-level Flagger" - may need custom controller
- Or: adapt Flagger's analysis/rollback logic with custom traffic shifting

## Alternative: Actor-level interceptor routers

A/B/N testing could be implemented purely at the actor level using **interceptor routers**:

**Concept:**
- Instead of routing to `model`, route to `model-router`
- `model-router` is a lightweight actor that:
  1. Reads experiment config (from ConfigMap, env, or external service)
  2. Decides variant based on weights, headers, or MAB algorithm
  3. Rewrites `route.actors` to point to `model-a`, `model-b`, etc.
  4. Passes envelope through

**Example flow:**
```
gateway → preprocess → model-router → model-a (80%) → postprocess
                                   ↘ model-b (20%) → postprocess
```

**Pros:**
- No framework changes required - works with current Asya
- Users control experiment logic in Python (full flexibility)
- Easy to add custom MAB algorithms, sticky sessions, etc.
- Composable - can have multiple experiment points in a flow

**Cons:**
- Extra hop (latency) for every experimented actor
- User must implement router logic (or we provide a library)
- Experiment config management is user's responsibility

**Implementation options:**
1. **User-written routers** - full control, more work
2. **asya-crew experiment actor** - generic router configured via env/ConfigMap
3. **Flow DSL `experiment()` block** - compiler generates router automatically

**Sticky session handling:**
- Router reads `headers.x-asya-session-id` or similar
- Consistent hashing to ensure same user → same variant
- Or: router sets `headers.x-asya-variant` for downstream tracking


---
_Migrated from beads `asya-dl2`_
