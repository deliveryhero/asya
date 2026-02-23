---
title: "Research: Actor warm-up pattern before scale-to-zero"
priority: 3 # low
type: task
---



Research and design a warm-up pattern that ensures actors are validated as healthy before allowing KEDA to scale them to zero.

## Problem

When an AsyncActor has KEDA autoscaling with minReplicas=0, a broken actor can scale to zero before ever being validated:

1. User creates AsyncActor with broken handler code
2. KEDA sees no messages → scales to 0
3. Status shows 'Napping' (looks healthy!)
4. First real message → pod starts → CrashLoopBackOff
5. User discovers actor was broken all along

## Desired Behavior

Actor must successfully start at least once (pods healthy, probes OK) before it can scale to zero. 'Napping' status should mean 'verified healthy, just idle'.

## Research Questions

1. **Industry patterns**: How do similar tools handle this?
   - Knative Serving (scale-to-zero for HTTP)
   - AWS Lambda (cold start management)
   - Azure Container Apps
   - Google Cloud Run

2. **KEDA capabilities**: Does KEDA have built-in support?
   - initialCooldownPeriod
   - fallback.replicas
   - Custom metrics for health-gating

3. **Implementation options**:
   - Two-phase KEDA (minReplicas=1 → minReplicas=0 after warm)
   - Delayed KEDA creation (Deployment first, KEDA after healthy)
   - Composition Function for state tracking
   - Kubernetes readiness gates

4. **Performance impact**: Would delayed KEDA creation slow production deployments?

## Deliverables

- Document findings in docs/rfc/thoughts-actor-warm-up.md (already started)
- Recommend implementation approach
- Estimate complexity for each option
- Decision on whether to implement in Crossplane migration or defer further

## Reference

See docs/rfc/thoughts-actor-warm-up.md for initial exploration notes.


---
_Migrated from beads `asya-z31`_
