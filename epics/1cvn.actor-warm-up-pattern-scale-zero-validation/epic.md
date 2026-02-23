---
title: "Actor Warm-Up Pattern for Scale-to-Zero Validation"
status: open
priority: 4
type: epic
---

KEDA scale-to-zero can mask broken actors: a misconfigured AsyncActor scales down before it ever runs, appearing healthy until the first real message triggers a CrashLoopBackOff. This epic explores a warm-up pattern that forces at least one successful pod start (probes passing, sidecar connected) before allowing `minReplicas=0`, ensuring the "Napping" status genuinely reflects a working actor.

## RFC: Actor Warm-Up Pattern

### Problem Statement

When an AsyncActor has KEDA autoscaling enabled with `minReplicas=0`, the actor can scale to zero before ever being validated as healthy. This creates a scenario where:

1. User creates AsyncActor with broken handler code
2. KEDA sees no messages in queue → scales to 0
3. Status shows "Ready 0/0" or "Napping" (looks healthy!)
4. First real message arrives → pod starts → CrashLoopBackOff
5. User discovers the actor was broken all along

### Desired Behavior

Actor must successfully start at least once (pods healthy, liveness/startup probes OK) before it can scale to zero. This ensures:
- Broken actors are detected immediately at deploy time
- "Napping" status is trustworthy (actor CAN work, just idle)

### Proposed Lifecycle

```
[Created] ──► [Warming] ──► [Warmed] ──► [Napping]
                 │              │            │
           minReplicas=1   minReplicas=0   (scaled to 0 by KEDA)
           (forced start)  (can scale to zero)
```

Transition `Warming → Warmed` happens when:
- `readyReplicas >= 1`
- All pod probes (startup, liveness, readiness) healthy
- Sidecar connected to queue successfully

### Implementation Options

#### Option A: Two-Phase KEDA Configuration

1. Composition Function creates KEDA ScaledObject with `minReplicas=1`
2. Function watches Deployment status
3. When `readyReplicas >= 1` for N seconds, update KEDA to `minReplicas=0`
4. Store `asya.sh/warmed-at` annotation on Deployment

**Pros**: Clean state machine
**Cons**: Requires Composition Function, potential race conditions

#### Option B: Delayed KEDA Creation

1. Crossplane creates Deployment with `replicas=1` (no KEDA yet)
2. Wait for Deployment to be healthy
3. Create KEDA ScaledObject with `minReplicas=0`

**Pros**: Simple logic
**Cons**: Slower on high load? Need to measure latency impact

#### Option C: KEDA initialCooldownPeriod

Use KEDA's built-in `advanced.horizontalPodAutoscalerConfig.behavior.scaleDown.stabilizationWindowSeconds`

**Pros**: No custom code
**Cons**: Time-based, not health-based. 5-minute delay regardless of actual health.

#### Option D: KEDA Fallback Configuration

Set `fallback.replicas=1` so if scaling fails, KEDA keeps 1 replica running.

**Pros**: Simple, built-in KEDA feature
**Cons**: Doesn't prevent initial scale-to-zero, only handles scaler failures

### Open Questions

1. **Is this a standard pattern?** Research how similar tools handle this:
   - Knative Serving (scale-to-zero for HTTP)
   - AWS Lambda (cold start management)
   - Azure Container Apps (scale-to-zero)

2. **Does KEDA have built-in support?**
   - Check if `minReplicaCount` can be dynamic
   - Check if there's a "warm-up" or "initial scale" feature
   - Research KEDA GitHub issues for similar requests

3. **Performance impact of Option B?**
   - Measure: Time from AsyncActor creation to KEDA active
   - Concern: In production with many actors, would staggered KEDA creation cause issues?

4. **Can we use Kubernetes readiness gates?**
   - Custom readiness gate that blocks pod ready until warm-up complete
   - Might interact poorly with KEDA's replica counting

### Research Links

- KEDA Fallback: https://keda.sh/docs/2.12/concepts/scaling-deployments/#fallback
- KEDA ScaledObject spec: https://keda.sh/docs/2.12/concepts/scaling-deployments/
- Knative scale-to-zero: https://knative.dev/docs/serving/autoscaling/scale-to-zero/

### Recommendation

For initial implementation: **Skip warm-up**. Accept that:
- "Napping" status means scaled-to-zero (may or may not be healthy)
- First-time broken actors will fail on first message
- Users should test actors with messages before relying on scale-to-zero

Add warm-up in future iteration once basic Crossplane migration is stable.
