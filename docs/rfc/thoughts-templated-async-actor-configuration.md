# Thoughts: Templated AsyncActor Configuration (Profiles)

> **Status**: Future exploration
> **Date**: 2025-02-05
> **Related**: rfc-crossplane.md

## Problem Statement

Users want to avoid repetitive configuration when creating AsyncActors. Instead of specifying detailed scaling, resource, and timeout settings for every actor, they should be able to reference a **profile** that provides sensible defaults for their workload type.

**Current (verbose):**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-llm-actor
spec:
  transport: sqs
  scaling:
    minReplicas: 1
    maxReplicas: 4
    cooldownPeriod: 600
    pollingInterval: 30
  workload:
    image: my-llm:v1.0
    resources:
      limits:
        memory: "32Gi"
        cpu: "8"
        nvidia.com/gpu: "1"
```

**Desired (with profiles):**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-llm-actor
spec:
  profile: llm-heavy  # All defaults come from profile
  transport: sqs
  workload:
    image: my-llm:v1.0
```

## Requirements

1. **Pre-defined profiles** for common workload types (LLM inference, batch processing, real-time, etc.)
2. **Override capability** - users can override specific profile settings
3. **Easy to add new profiles** - no code changes, just YAML
4. **Scope options** - cluster-wide and optionally per-namespace

## Crossplane Implementation Options

### Option 1: Composition Selector with Labels (Recommended)

**How it works:**
- Create multiple Compositions for the same XRD
- Each Composition is labeled with its profile name
- User selects profile via `compositionSelector.matchLabels`

**Example Compositions:**

```yaml
# Profile: default
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: asyncactor-sqs-default
  labels:
    asya.sh/profile: default
    asya.sh/transport: sqs
spec:
  compositeTypeRef:
    apiVersion: asya.sh/v1alpha1
    kind: XAsyncActor
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: sqs-queue
            base:
              apiVersion: sqs.aws.upbound.io/v1beta1
              kind: Queue
              spec:
                forProvider:
                  visibilityTimeoutSeconds: 30
                  messageRetentionSeconds: 345600
          # Default scaling: 0-10 replicas
          # Default resources: 256Mi memory, 100m CPU
```

```yaml
# Profile: llm-heavy
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: asyncactor-sqs-llm-heavy
  labels:
    asya.sh/profile: llm-heavy
    asya.sh/transport: sqs
spec:
  compositeTypeRef:
    apiVersion: asya.sh/v1alpha1
    kind: XAsyncActor
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: sqs-queue
            base:
              apiVersion: sqs.aws.upbound.io/v1beta1
              kind: Queue
              spec:
                forProvider:
                  visibilityTimeoutSeconds: 300  # Longer for LLM inference
                  messageRetentionSeconds: 604800  # 7 days
          # LLM scaling: 1-4 replicas (never scale to zero)
          # LLM resources: 32Gi memory, 8 CPU, 1 GPU
```

**User selects profile:**
```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: my-llm-actor
spec:
  compositionSelector:
    matchLabels:
      asya.sh/profile: llm-heavy
  transport: sqs
  workload:
    image: my-llm:v1.0
```

**Pros:**
- No custom code needed
- Standard Crossplane pattern
- Easy to add profiles (just create new Composition)
- Clear separation of concerns

**Cons:**
- Compositions are cluster-scoped (same profile = same settings everywhere)
- Requires one Composition per profile × transport combination
- User overrides require understanding patch priority

---

### Option 2: EnvironmentConfigs for Namespace-Scoped Profiles

**How it works:**
- Store profile configurations in EnvironmentConfig resources
- EnvironmentConfigs can be namespace-scoped
- Composition reads from EnvironmentConfig in claim's namespace

**Profile stored as EnvironmentConfig:**
```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: EnvironmentConfig
metadata:
  name: profile-llm-heavy
  namespace: prod  # Namespace-scoped!
  labels:
    asya.sh/profile: llm-heavy
data:
  scaling:
    minReplicas: 1
    maxReplicas: 8  # Higher in prod
    cooldownPeriod: 600
  resources:
    limits:
      memory: "64Gi"  # More memory in prod
      nvidia.com/gpu: "2"  # More GPUs in prod
```

```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: EnvironmentConfig
metadata:
  name: profile-llm-heavy
  namespace: dev  # Different values in dev
  labels:
    asya.sh/profile: llm-heavy
data:
  scaling:
    minReplicas: 0
    maxReplicas: 2  # Lower in dev
  resources:
    limits:
      memory: "16Gi"
      nvidia.com/gpu: "1"
```

**Composition references EnvironmentConfig:**
```yaml
spec:
  environment:
    environmentConfigs:
      - type: Selector
        selector:
          matchLabels:
            - key: asya.sh/profile
              type: FromCompositeFieldPath
              valueFromFieldPath: spec.profile
```

**Pros:**
- Namespace-scoped profiles
- Same profile name can mean different things in different namespaces
- GitOps-friendly (profiles are just YAML resources)

**Cons:**
- More complex setup
- Requires EnvironmentConfig per profile × namespace
- Crossplane v2 feature (may need migration)

---

### Option 3: Custom Composition Function

**How it works:**
- Write a Go/Python Composition Function
- Function reads profile name from spec
- Function applies defaults from built-in or ConfigMap-based profiles

**Example function input:**
```yaml
pipeline:
  - step: apply-profile
    functionRef:
      name: function-asya-profiles
    input:
      apiVersion: asya.sh/v1alpha1
      kind: ProfileConfig
      profiles:
        default:
          scaling:
            minReplicas: 0
            maxReplicas: 10
          resources:
            limits:
              memory: "256Mi"
        llm-heavy:
          scaling:
            minReplicas: 1
            maxReplicas: 4
            cooldownPeriod: 600
          resources:
            limits:
              memory: "32Gi"
              nvidia.com/gpu: "1"
        batch-processing:
          scaling:
            minReplicas: 0
            maxReplicas: 100
            pollingInterval: 10
```

**Pros:**
- Full programmatic control
- Can implement complex logic (templated names, inheritance)
- Single Composition handles all profiles

**Cons:**
- Requires writing and maintaining Go/Python code
- More complex deployment (function container)
- Harder to add profiles (requires code change or ConfigMap)

---

### Option 4: Composition Function + Namespace ConfigMaps

**How it works:**
- Profiles stored in ConfigMaps per namespace
- Composition Function reads ConfigMap from claim's namespace
- Applies profile defaults from ConfigMap

**ConfigMap per namespace:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: asya-profiles
  namespace: prod
data:
  llm-heavy: |
    scaling:
      minReplicas: 1
      maxReplicas: 8
    resources:
      limits:
        memory: "64Gi"
        nvidia.com/gpu: "2"
  batch: |
    scaling:
      minReplicas: 0
      maxReplicas: 100
```

**Pros:**
- Namespace-scoped
- Platform team can manage profiles per namespace
- Users just reference profile name

**Cons:**
- Requires custom Composition Function
- ConfigMap management overhead

---

## Recommended Approach

### Phase 1: Composition Selector (Cluster-Wide)

Start simple with cluster-wide profiles using Composition Selector:

1. Create Compositions for common profiles: `default`, `llm-heavy`, `batch-processing`, `real-time`
2. Add `compositionSelector` or `profile` field to XRD
3. Document available profiles

**Effort:** Low (just YAML)
**Flexibility:** Cluster-wide only

### Phase 2: EnvironmentConfigs (Namespace-Scoped)

Add namespace-scoped overrides:

1. Define base profiles as cluster-wide Compositions
2. Allow namespace-specific overrides via EnvironmentConfigs
3. Merge order: Composition defaults → EnvironmentConfig → User spec

**Effort:** Medium (EnvironmentConfig setup)
**Flexibility:** Full namespace isolation

### Phase 3: Custom Function (Advanced)

If needed for complex requirements:

1. Build `function-asya-profiles` for advanced logic
2. Support profile inheritance, templated fields
3. Read profiles from ConfigMaps or built-in

**Effort:** High (Go code)
**Flexibility:** Unlimited

---

## Suggested Profile Catalog

| Profile | Use Case | Key Settings |
|---------|----------|--------------|
| `default` | General purpose | 0-10 replicas, 256Mi memory |
| `llm-heavy` | LLM inference (GPT, embeddings) | 1-4 replicas, 32Gi memory, GPU |
| `llm-light` | Small LLMs (distilled models) | 0-8 replicas, 8Gi memory |
| `batch-processing` | High-throughput batch | 0-100 replicas, fast polling |
| `real-time` | Low-latency processing | 2-20 replicas, short cooldown |
| `gpu-inference` | Generic GPU workloads | 1-4 replicas, GPU required |
| `memory-heavy` | Large in-memory processing | 0-10 replicas, 64Gi memory |

---

## XRD Schema Changes

Add `profile` field and `compositionSelector`:

```yaml
spec:
  properties:
    profile:
      type: string
      description: Pre-defined configuration profile
      enum:
        - default
        - llm-heavy
        - llm-light
        - batch-processing
        - real-time
        - gpu-inference
        - memory-heavy
      default: default

    compositionSelector:
      type: object
      description: Advanced composition selection (overrides profile)
      properties:
        matchLabels:
          type: object
          additionalProperties:
            type: string
```

**Syntactic sugar:** If user specifies `profile: llm-heavy`, translate to:
```yaml
compositionSelector:
  matchLabels:
    asya.sh/profile: llm-heavy
    asya.sh/transport: <from spec.transport>
```

---

## Scope Considerations

### Cluster-Wide Profiles

**When to use:**
- Same profile means same settings everywhere
- Central platform team manages all profiles
- Simpler mental model

**Implementation:** Composition Selector

### Namespace-Scoped Profiles

**When to use:**
- Different environments need different defaults (dev vs prod)
- Teams want to customize profiles for their namespace
- Need to limit resources per namespace

**Implementation:** EnvironmentConfigs or ConfigMaps

### Hierarchy (if combining)

```
1. Cluster-wide Composition (base)
       ↓
2. Namespace EnvironmentConfig (overrides)
       ↓
3. User AsyncActor spec (final overrides)
```

---

## Open Questions

1. **Should `profile` be a first-class field or just use `compositionSelector`?**
   - First-class is more user-friendly
   - compositionSelector is more flexible

2. **How to handle profile × transport combinations?**
   - One Composition per combination (profile × transport)
   - Or single Composition with conditional patches

3. **Can users create custom profiles?**
   - Platform team only (controlled via RBAC on Compositions)
   - Or allow user-defined profiles in their namespace

4. **Profile inheritance?**
   - `llm-light` inherits from `llm-heavy` with overrides
   - Requires Composition Function for implementation

5. **Validation of profile + override combinations?**
   - What if user specifies `profile: llm-heavy` but overrides GPU to 0?
   - Warn? Error? Allow?

---

## References

- [Crossplane Compositions](https://docs.crossplane.io/latest/concepts/compositions/)
- [Crossplane EnvironmentConfigs](https://docs.crossplane.io/latest/concepts/environment-configs/)
- [Composition Functions](https://docs.crossplane.io/latest/concepts/composition-functions/)
- [function-patch-and-transform](https://github.com/crossplane-contrib/function-patch-and-transform)
