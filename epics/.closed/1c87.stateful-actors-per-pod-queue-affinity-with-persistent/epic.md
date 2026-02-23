---
title: Stateful Actors — Per-Pod Queue Affinity with Persistent Storage
status: yeeted
priority: 2 # medium
type: epic
---



Stateful actors are the foundation for fan-in aggregation and other shard-affine workloads in Asya. This epic introduces StatefulSet-based pods where each pod consumes from its own dedicated queue, enabling deterministic message routing via rendezvous hashing. Persistent storage is provided through standard K8s `volumeClaimTemplates`, and shard resolution is handled externally by the sender using existing `x-asya-route-override` headers.

## RFC: Stateful Actors — Per-Pod Queue Affinity

- **Status**: Draft
- **Date**: 2026-02-16
- **Authors**: Artem Yushkovskiy
- **Related**: [Fan-In RFC](rfc-fan-in.md), [Actor Flavors RFC](../actor-flavors/rfc-actor-flavors.md), [A/B Routing RFC](../a-b-testing/rfc-a-b-routing.md)

## Abstract

This RFC introduces **stateful actors** as a general-purpose primitive in Asya. A stateful actor runs as a Kubernetes StatefulSet where each pod consumes from its own dedicated queue, enabling shard-affine message routing. Persistent storage is provided via standard K8s `volumeClaimTemplates`. Shard resolution is handled externally by the sender (via `x-asya-route-override` headers), keeping the sidecar and stateful actor itself unaware of sharding mechanics.


## Future use-cases

Fan-in aggregation is the first use case but the primitive supports any workload requiring message affinity, in future we'll support more use-cases:

|Use case|Sharding key|State|
|-|-|-|
|Fan-in aggregation|`origin_id`|Partial results in RocksDB|
|Session/conversation memory|`user_id` or `session_id`|Chat history, context|
|Deduplication|`message_id`|Seen IDs with TTL|
|Time-window batching|`batch_key`|Accumulated events|
|Per-key rate limiting|`client_id`|Request counters|


## Motivation

Asya's current actor model is stateless: all pods of an actor compete for messages from a single shared queue. This works for independent request processing but breaks when messages must reach a **specific pod** — for example, all slices of a fan-out operation must converge on the same aggregator replica to detect completeness.

### Requirements

- **Shard affinity**: Messages with the same key reach the same pod deterministically
- **Durability**: State survives pod restarts (PVC-backed storage)
- **Transport-agnostic**: Works with SQS, RabbitMQ, and future transports
- **Minimal sidecar changes**: The sidecar should not need sharding logic
- **K8s-native**: Leverage StatefulSet, volumeClaimTemplates, downward API (?), existing integration with Crossplane, KEDA
- **Explicit configuration and composition**: XRD `AsyncActor` should define stateful set configuration explicitly, and we'll leverage existing mechanism of *flavors* and *asya-crew* pre-built actors to make it less verbose and offer re-usable actors.

---

## Design

### Queue Model

Stateless actors: **1 queue, M competing pods** (Deployment).
Stateful actors: **N queues, N dedicated pods** (StatefulSet). Each pod consumes exclusively from its own queue (however, on the asya level, in `message.route`, this queue looks still like the same: `asya-{ns}-{actor}` as it's the same actor).

```
Stateless: asya-{ns}-{actor}        ← all pods compete
Stateful:  asya-{ns}-{actor}-0      ← pod 0 only
           asya-{ns}-{actor}-1      ← pod 1 only
           asya-{ns}-{actor}-2      ← pod 2 only
```

This is the only mechanism that provides **hard shard affinity** across all transports without introducing pod-to-pod communication. Transport-level alternatives (SQS FIFO message groups, RabbitMQ consistent-hash exchange) either lack hard guarantees or hide N queues behind an exchange — and each is transport-specific.

### XRD Schema Extension

Add an optional `stateful` object to the AsyncActor spec. Its presence switches the composition to StatefulSet mode with per-pod queues.

```yaml
# New fields in the AsyncActor XRD under spec
stateful:
  type: object
  description: |
    Enables stateful actor mode: StatefulSet workload, per-pod queues
    with shard-affine routing, and optional persistent storage.
    When present, overrides workload kind to StatefulSet.
  properties:
    preCreateQueues:
      type: integer
      minimum: 1
      description: |
        Number of queues to pre-provision at deploy time (indices 0 to
        preCreateQueues-1). Should be >= scaling.maxReplicas if autoscaling
        is enabled. Defaults to scaling.maxReplicas (if scaling configured)
        or workload.replicas (if not).
    volumeClaimTemplates:
      type: array
      description: |
        K8s-native volumeClaimTemplates, passed directly to the StatefulSet
        spec. Each template creates one PVC per pod.
      items:
        type: object
        x-kubernetes-preserve-unknown-fields: true
```

**Key properties:**

- `stateful` is optional. Absence = stateless (current behavior, no breaking changes)
- **No `replicas` field** — uses existing `workload.replicas` (no scaling) or `scaling.minReplicas/maxReplicas` (with KEDA)
- `preCreateQueues` controls headroom for scale-up without queue-creation races
- `volumeClaimTemplates` is optional (a stateful actor might only need queue affinity, not storage)
- `volumeClaimTemplates` uses the standard K8s schema — users get full PVC control (access modes, storage classes, selectors for binding to pre-provisioned PVs)

### Queue Pre-Provisioning

Queues are pre-provisioned at deploy time to eliminate race conditions on scale-up. Unlike PVCs, idle queues are free (SQS) or negligible (RabbitMQ).

| Resource | Pre-provisioned? | Rationale |
|----------|-----------------|-----------|
| Queues   | ✅ Up to `preCreateQueues` | Free when idle, eliminates scale-up races |
| PVCs     | ❌ On-demand by StatefulSet controller | Cost real storage, dynamic provisioning is fast |

**Default formula** for `preCreateQueues` when not explicitly set:

```
if spec.scaling is present:
    preCreateQueues = scaling.maxReplicas
else:
    preCreateQueues = workload.replicas  (default: 1)
```

### Pod Identity and Queue Resolution

Each StatefulSet pod determines its queue name at startup via K8s-native mechanisms:

```yaml
# Injected into the sidecar container by the operator/injector
env:
  - name: ASYA_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  - name: ASYA_ACTOR_NAME
    value: "my-aggregator"
  - name: ASYA_POD_INDEX
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['apps.kubernetes.io/pod-index']
  - name: ASYA_QUEUE_NAME
    value: "asya-$(ASYA_NAMESPACE)-$(ASYA_ACTOR_NAME)-$(ASYA_POD_INDEX)"
```

For stateless actors, `ASYA_QUEUE_NAME` omits the pod index:

```yaml
  - name: ASYA_QUEUE_NAME
    value: "asya-$(ASYA_NAMESPACE)-$(ASYA_ACTOR_NAME)"
```

The sidecar reads `ASYA_QUEUE_NAME` and consumes from it. **No sharding logic in the sidecar.** The sidecar does not know whether it is stateful or stateless — it just consumes from the queue it is told to consume from.

**`apps.kubernetes.io/pod-index`** is a stable K8s label (GA since K8s 1.29) automatically added by the StatefulSet controller to every pod. It is reliable — every major stateful system on K8s (Kafka, Cassandra, etcd) relies on this convention.

### Shard Routing

Shard routing uses the existing `x-asya-route-override` mechanism from the [A/B routing RFC](../a-b-testing/rfc-a-b-routing.md). **No new headers or sidecar logic required.**

The sender (e.g., fan-out router) computes the target shard and stamps the override:

```python
shard = rendezvous_hash(origin_id, num_shards)
headers["x-asya-route-override"] = {"aggregator": f"aggregator-{shard}"}
```

The sidecar's existing route-override lookup resolves `"aggregator"` to `"aggregator-2"`, constructs the queue name `asya-{ns}-aggregator-2`, and sends the message. No sidecar changes needed for the routing path.

**Shard count propagation**: The sender learns the shard count via an environment variable (e.g., `ASYA_FANIN_SHARDS`). When the aggregator scales, this env var is updated on the sender's AsyncActor, triggering a rolling restart. This is acceptable because the sender is a stateless actor with fast restarts.

### Composition Changes

The existing composition gains conditional logic when `spec.stateful` is present:

| Concern | Stateless (current) | Stateful (new) |
|---------|---------------------|----------------|
| Workload | Deployment | StatefulSet with volumeClaimTemplates |
| Queues | 1: `asya-{ns}-{actor}` | N: `asya-{ns}-{actor}-0` .. `asya-{ns}-{actor}-{N-1}` |
| Sidecar env | `ASYA_QUEUE_NAME` = `asya-{ns}-{actor}` | `ASYA_QUEUE_NAME` = `asya-{ns}-{actor}-{pod_index}` |
| KEDA target | `scaleTargetRef.kind: Deployment` | `scaleTargetRef.kind: StatefulSet` |
| Status | `queueUrl`: single URL | `queuePattern`: `asya-{ns}-{actor}-{0..N-1}` |

**Queue rendering** (Go template pseudo-logic):

```go
{{ if $xr.spec.stateful }}
  {{ $n := $xr.spec.stateful.preCreateQueues | default $maxReplicas | default $replicas }}
  {{ range $i := until $n }}
    - kind: Queue
      metadata:
        name: {{ $actorName }}-{{ $i }}
      spec:
        forProvider:
          name: asya-{{ $namespace }}-{{ $actorName }}-{{ $i }}
  {{ end }}
{{ else }}
  - kind: Queue
    metadata:
      name: {{ $actorName }}
    spec:
      forProvider:
        name: asya-{{ $namespace }}-{{ $actorName }}
{{ end }}
```

### Status Reporting

Stateful actors report a queue pattern instead of a single URL:

```yaml
status:
  phase: Ready
  queuePattern: "asya-prod-my-aggregator-{0..9}"
  infrastructure:
    queue: "Ready"
    workload: "Ready"
```

### Autoscaling (Phased)

Stateful actor autoscaling is delivered in three phases:

**Phase 1 — Semi-automatic (foundation)**

- Manual scaling: user updates `workload.replicas` or `scaling.minReplicas`
- Operator adjusts StatefulSet replicas
- Pre-provisioned queues ensure no races
- User updates `ASYA_FANIN_SHARDS` on the sender and triggers rolling restart

**Phase 2 — Auto scale-up**

- KEDA ScaledObject with `scaleDown.selectPolicy: Disabled`
- Prometheus trigger on PVC utilization or custom metrics
- Operator watches StatefulSet replica changes, propagates shard count to senders (e.g., via ConfigMap or env var update)
- Fan-out sidecars hot-reload N or sender pods rolling-restart

```yaml
scaling:
  minReplicas: 3
  maxReplicas: 10
  triggers:
    - type: prometheus
      metadata:
        query: |
          max(asya_fanin_rocksdb_size_bytes{actor="aggregator"})
          / on() group_left() asya_fanin_pvc_capacity_bytes
        threshold: "0.7"
```

```yaml
# KEDA behavior: scale-up only
advanced:
  horizontalPodAutoscaperConfig:
    behavior:
      scaleDown:
        selectPolicy: Disabled
```

**Phase 3 — Auto scale-down (separate RFC if needed)**

Scale-down is hard for stateful actors. KEDA removes pods from the tail (highest ordinal first), but that pod has in-flight state in its storage.

Requirements for safe scale-down:
1. Stop routing new messages to the condemned shard (update shard count before pod removal)
2. Drain in-flight state (pre-stop hook or finalizer blocks termination until storage is empty)
3. Timeout for drain completion

This requires a stateful-actor-aware controller sitting between KEDA's scaling decision and the actual pod removal. Deferred to a future RFC.

---

## Examples

### Example 1: Minimal Stateful Actor (Queue Affinity Only)

A stateful actor that needs message affinity but no persistent storage (e.g., in-memory session cache):

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: session-cache
  namespace: prod
spec:
  actor: session-cache
  transport: sqs
  workload:
    replicas: 3
    template:
      spec:
        containers:
          - name: asya-runtime
            image: my-app:latest
            env:
              - name: ASYA_HANDLER
                value: "session.handle_request"
  stateful: {}
```

**Result**: 3-pod StatefulSet, 3 queues (`session-cache-0`, `session-cache-1`, `session-cache-2`), no PVCs.

### Example 2: Fan-In Aggregator with RocksDB Storage

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator
  namespace: prod
spec:
  actor: aggregator
  transport: sqs
  flavors: [fan-in-rocksdb]
  stateful:
    preCreateQueues: 10
    volumeClaimTemplates:
      - metadata:
          name: data
        spec:
          accessModes: ["ReadWriteOnce"]
          storageClassName: gp3
          resources:
            requests:
              storage: 10Gi
  workload:
    template:
      spec:
        containers:
          - name: asya-runtime
            image: asya-crew:latest
            env:
              - name: ASYA_HANDLER
                value: "asya_crew.aggregator.handle"
              - name: ASYA_HANDLER_MODE
                value: "envelope"
            volumeMounts:
              - name: data
                mountPath: /data/aggregator
  scaling:
    minReplicas: 3
    maxReplicas: 10
```

**Result**: StatefulSet with 3 replicas, 10 pre-provisioned queues, per-pod 10Gi PVC at `/data/aggregator`, KEDA watches queue depth with scale-down disabled.

### Example 3: Fan-In Aggregator with Flavor (Minimal User Config)

The `fan-in-rocksdb` flavor provides sensible defaults for image, handler, resources, volumeMounts, and scaling:

```yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator
  namespace: prod
spec:
  actor: aggregator
  transport: sqs
  flavors: [fan-in-rocksdb]
  stateful:
    volumeClaimTemplates:
      - metadata:
          name: data
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
```

The flavor fills in `image`, `handler`, `handlerMode`, `resources`, `volumeMounts`, and `scaling.minReplicas: 1`. The user only specifies transport, storage size, and the flavor name.

### Example 4: Complete Fan-Out/Fan-In Pipeline

Three independent AsyncActor deployments form a fan-out/fan-in pipeline:

```yaml
# 1. Fan-out router (stateless, compiler-generated)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: fanout-research
spec:
  actor: fanout-research
  transport: sqs
  workload:
    template:
      spec:
        containers:
          - name: asya-runtime
            image: my-flow-routers:latest
            env:
              - name: ASYA_HANDLER
                value: "routers.fanout_research"
              - name: ASYA_HANDLER_MODE
                value: "envelope"
              - name: ASYA_FANIN_SHARDS
                value: "3"
---
# 2. Sub-agent (stateless, user-provided)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: research-agent
spec:
  actor: research-agent
  transport: sqs
  workload:
    replicas: 5
    template:
      spec:
        containers:
          - name: asya-runtime
            image: my-agents:latest
            env:
              - name: ASYA_HANDLER
                value: "agents.research"
---
# 3. Aggregator (stateful)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator
spec:
  actor: aggregator
  transport: sqs
  flavors: [fan-in-rocksdb]
  stateful:
    preCreateQueues: 6
    volumeClaimTemplates:
      - metadata:
          name: data
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
  scaling:
    minReplicas: 3
    maxReplicas: 6
```

**Message flow**:
1. Envelope arrives at `fanout-research` queue
2. Fan-out router computes `shard = rendezvous(origin_id, 3)`, stamps `x-asya-route-override: {"aggregator": "aggregator-{shard}"}` on all emitted messages
3. Sub-agent slices route through `research-agent` queue (competing consumers, 5 pods)
4. Sub-agent results carry the override header, sidecar routes to `aggregator-{shard}` queue
5. Aggregator pod `{shard}` accumulates slices in RocksDB, emits merged envelope on completeness

---

## Architecture Decision Records

### ADR-1: N Queues Per Stateful Actor (Not Shared Queue)

**Context**: Stateful actors need shard affinity — messages with the same key must reach the same pod. With a single shared queue, competing consumers distribute messages non-deterministically across pods.

| Option | Hard affinity? | Transport-agnostic? | Overhead |
|--------|---------------|---------------------|----------|
| Single queue, client-side filter (requeue non-matching) | ❌ O(N) wasted reads | ✅ | High (requeue storms, SQS cost) |
| SQS FIFO message groups | ❌ Soft guarantee | ❌ SQS-only | Low |
| RabbitMQ consistent-hash exchange | ❌ Hides N queues | ❌ RabbitMQ-only | Low |
| **N dedicated queues, one per pod** | **✅ Hard** | **✅** | **Negligible (idle queues are free)** |

**Decision**: One queue per pod. Queue name: `asya-{ns}-{actor}-{ordinal}`.

**Rationale**: Only option providing hard affinity across all transports. Idle queues cost nothing (SQS) or negligible memory (RabbitMQ). The queue is the routing mechanism in Asya — there is no concept of "send to queue X but only pod Y should get it."

### ADR-2: Pod Queue Identity via Downward API and Env Var Interpolation

**Context**: In a StatefulSet, all pods share the same pod template. Per-pod env vars (like `ASYA_QUEUE_NAME=aggregator-0` for pod 0) cannot be set statically. The sidecar needs to determine its queue name at startup.

| Option | Pros | Cons |
|--------|------|------|
| Hostname parsing (`aggregator-2` → ordinal 2) | Simple | Couples to StatefulSet/pod naming |
| K8s API query for pod metadata | Flexible | Adds K8s API dependency to sidecar |
| **Downward API: `apps.kubernetes.io/pod-index` label** | **K8s-native, label-based, reliable** | **Requires K8s 1.28+** |

**Decision**: Use `ASYA_POD_INDEX` env var populated via downward API from the `apps.kubernetes.io/pod-index` label (GA since K8s 1.29). Construct `ASYA_QUEUE_NAME` via K8s env var interpolation:

```yaml
- name: ASYA_QUEUE_NAME
  value: "asya-$(ASYA_NAMESPACE)-$(ASYA_ACTOR_NAME)-$(ASYA_POD_INDEX)"
```

**Rationale**: Label-based identity is consistent with Asya's existing design (actor identity from `asya.sh/actor` label, not pod name). No hostname parsing, no K8s API access, no init containers. The sidecar sees a fully-constructed `ASYA_QUEUE_NAME` — zero knowledge of statefulness required.

**Consequence**: `ASYA_QUEUE_NAME` is set for **all** actors (stateful and stateless). The sidecar always reads it. This unifies the queue name interface and removes the sidecar's internal `resolveQueueName` derivation for the consumption path.

### ADR-3: Shard Routing via x-asya-route-override (No New Header)

**Context**: Messages targeting a stateful actor need to reach the correct shard. Two approaches were considered:

| Option | Sidecar changes | Complexity |
|--------|----------------|------------|
| New `x-asya-shard-key` header, sidecar computes shard | Sidecar needs ConfigMap awareness, rendezvous hash, shard lookup | High |
| **`x-asya-route-override` (existing A/B routing mechanism)** | **None** | **None** |

**Decision**: The sender (fan-out router) computes the shard and stamps `x-asya-route-override: {"aggregator": "aggregator-2"}`. The sidecar's existing override lookup handles routing. No new sidecar logic.

**Rationale**: The `x-asya-route-override` mechanism from the A/B routing RFC already solves "resolve abstract actor name to concrete queue." Reusing it for shard resolution means zero sidecar changes on the routing path. The fan-out router is the natural place for shard computation — it already knows the shard count (via `ASYA_FANIN_SHARDS` env var) and the origin ID.

**Consequence**: Only the sender needs shard awareness. The stateful actor itself, sub-agents, and their sidecars are all unaware of sharding. This keeps the system simple but means shard count changes require updating the sender's env var (see ADR-6).

### ADR-4: Queue Pre-Provisioning with Configurable Headroom

**Context**: When KEDA scales a StatefulSet from 3 to 4 replicas, pod `aggregator-3` starts and its sidecar tries to consume from `asya-{ns}-aggregator-3`. If that queue doesn't exist yet, the sidecar fails on startup.

| Option | Race-free? | Cost |
|--------|-----------|------|
| Create queue on scale-up (operator watches replica changes) | ❌ Race between pod start and queue creation | Free |
| **Pre-provision queues up to a configurable limit** | **✅** | **Free (SQS idle queues cost nothing)** |

**Decision**: Pre-provision queues at deploy time. The `preCreateQueues` field controls how many. Default: `scaling.maxReplicas` if scaling is configured, else `workload.replicas`.

**Rationale**: Idle queues are free on SQS and negligible on RabbitMQ. Pre-provisioning eliminates the race condition entirely — the queue always exists before the pod starts. The configurable field gives users explicit control over headroom.

### ADR-5: Extend Existing AsyncActor (Not Separate CRD)

**Context**: Stateful actors need StatefulSet, per-pod queues, and optional PVCs. Should this be a new CRD (`StatefulActor`) or an extension of `AsyncActor`?

| Option | Pros | Cons |
|--------|------|------|
| New `StatefulActor` CRD | Clean separation, independent evolution | Two CRDs to learn, duplicated composition logic, flavors need dual support |
| **`spec.stateful` section on existing AsyncActor** | **One CRD, one composition, flavors work as-is** | **Composition gains conditional logic** |

**Decision**: Add `spec.stateful` to AsyncActor. Its presence implies StatefulSet + per-pod queues.

**Rationale**: A stateful actor IS an async actor with additional infrastructure concerns. Sharing the CRD means the entire flavor system, scaling configuration, resiliency settings, and transport configuration work unchanged. The composition's conditional logic is straightforward (`{{ if .spec.stateful }}`).

### ADR-6: Env Var for Shard Count Propagation

**Context**: The fan-out router needs to know the aggregator's shard count to compute rendezvous hashes. This value must be available at runtime.

| Option | Dynamic? | Complexity |
|--------|----------|------------|
| Compile-time constant in generated code | ❌ Requires recompilation | Low |
| **Env var (`ASYA_FANIN_SHARDS`) on sender** | **❌ Requires rolling restart** | **Low** |
| ConfigMap mounted as volume, sidecar watches | ✅ Hot-reload in ~60s | Medium |
| Sidecar queries K8s API for StatefulSet replicas | ✅ Real-time | High (K8s API dependency) |

**Decision**: Env var on the sender's AsyncActor. Shard count changes trigger a rolling restart of the sender.

**Rationale**: Simplest option. The sender (fan-out router) is a stateless actor — rolling restarts are fast and safe. The two-step manual process (scale aggregator, then update sender's env var) is acceptable for phase 1. Phase 2 (auto scale-up) can introduce operator-managed propagation.

**Downsides** (acceptable):
- Two-step coordination: scale aggregator, then update sender env var
- Brief window during rolling restart where some sender pods use old N and some use new N (harmless — each fan-out is internally consistent)
- Multiple aggregators require multiple env vars (`ASYA_FANIN_SHARDS_AGG_A=3`, `ASYA_FANIN_SHARDS_AGG_B=5`)

### ADR-7: K8s-Native volumeClaimTemplates Pass-Through

**Context**: Stateful actors need persistent storage. Should the XRD define a custom storage abstraction or pass through K8s-native volumeClaimTemplates?

| Option | Pros | Cons |
|--------|------|------|
| Custom `storage: {size, mountPath, storageClass}` | Simple for common case | Loses K8s flexibility (access modes, selectors, labels) |
| **K8s-native volumeClaimTemplates** | **Full PVC control, composable with K8s tools** | **More verbose** |

**Decision**: Pass `volumeClaimTemplates` verbatim to the StatefulSet spec. Mount points are defined in `workload.template.spec.containers[].volumeMounts` (standard K8s).

**Rationale**: K8s users already know volumeClaimTemplates. Custom abstractions hide capabilities (access modes, label selectors for binding to pre-provisioned PVs, storage class selection). The `fan-in-rocksdb` flavor can provide sensible defaults, reducing verbosity for the common case while preserving full flexibility.

**Consequence**: The volume mount path is defined separately in `workload.template`, not in `stateful`. This follows K8s separation of "what storage" (volumeClaimTemplates) from "where to mount" (volumeMounts).

### ADR-8: Reuse Existing Replica Count Fields

**Context**: The XRD already has `workload.replicas` (no scaling) and `scaling.minReplicas/maxReplicas` (with KEDA). Should `stateful` define its own replica count?

| Option | Pros | Cons |
|--------|------|------|
| `stateful.replicas` | Explicit | Third place to set replica count, contradicts existing fields |
| **Reuse existing fields** | **No contradiction, one mental model** | **None** |

**Decision**: No replica count in `stateful`. The composition uses:
- `workload.replicas` if no scaling section (for fixed-size stateful actors)
- `scaling.minReplicas` as initial replica count (when KEDA is configured)

**Rationale**: Adding `stateful.replicas` alongside `workload.replicas` and `scaling.minReplicas` creates ambiguity about which one wins. Reusing existing fields keeps the mental model simple: "stateful changes HOW pods are deployed, not HOW MANY."

The `fan-in-rocksdb` flavor sets `scaling.minReplicas: 1` as a sensible default (stateful actors should not scale to zero by default since PVC creation adds latency on cold start).

### ADR-9: Single Composition with Conditional Logic

**Context**: The stateful actor behavior could be implemented as a separate composition or as conditional logic in the existing one.

| Option | Pros | Cons |
|--------|------|------|
| Separate compositions (`composition-sqs-stateful.yaml`) | Simpler per-file | 4 compositions (2 transports x 2 modes), duplicated shared logic |
| Custom Composition Function | Base composition untouched | Another function to build/deploy/maintain |
| **Conditional logic in existing composition** | **No duplication, shared pipeline steps** | **Larger template files** |

**Decision**: Add `{{ if .spec.stateful }}` conditionals to existing compositions.

**Rationale**: The composition already handles workload rendering, KEDA configuration, and status aggregation. Adding conditional branches for queue loops and StatefulSet rendering avoids duplicating these shared steps. The conditionals are standard Go template patterns.

---

## Sidecar Changes Summary

| Change | Scope | Description |
|--------|-------|-------------|
| Read `ASYA_QUEUE_NAME` for consumption | Consumption path | Use env var instead of deriving queue name internally |
| No routing changes | Routing path | `x-asya-route-override` lookup is unchanged |

The sidecar currently derives its consumption queue name internally via `fmt.Sprintf("asya-%s-%s", namespace, actorName)`. The change is: read `ASYA_QUEUE_NAME` from env (set by the injector for all actors, stateful and stateless). This is a ~5-line change in the sidecar's startup code.

---

## Injector Changes Summary

The injector detects `spec.stateful` on the AsyncActor CRD and adjusts sidecar env vars:

| Actor type | `ASYA_QUEUE_NAME` | `ASYA_POD_INDEX` |
|------------|-------------------|------------------|
| Stateless  | `asya-$(ASYA_NAMESPACE)-$(ASYA_ACTOR_NAME)` | Not set |
| Stateful   | `asya-$(ASYA_NAMESPACE)-$(ASYA_ACTOR_NAME)-$(ASYA_POD_INDEX)` | Downward API: `metadata.labels['apps.kubernetes.io/pod-index']` |

---

## Use Cases Beyond Fan-In

| Use case | Shard key | State | Storage |
|----------|-----------|-------|---------|
| Fan-in aggregation | `origin_id` | Partial results | RocksDB (PVC) |
| Session/conversation memory | `user_id` or `session_id` | Chat history, context | RocksDB or SQLite (PVC) |
| Deduplication | `message_id` | Seen IDs with TTL | RocksDB (PVC) |
| Time-window batching | `batch_key` | Accumulated events | In-memory or PVC |
| Per-key rate limiting | `client_id` | Request counters | In-memory |

All use cases share the same infrastructure (StatefulSet, per-pod queues, optional PVC). The sender stamps `x-asya-route-override` with the concrete shard based on its chosen key. The stateful actor's handler implements the application-level logic.

---

## Open Questions

1. **KEDA trigger for StatefulSet**: When autoscaling a stateful actor, which queue(s) does KEDA monitor? Options: sum of all shard queue depths, max across shards, or a Prometheus metric (PVC utilization, RocksDB size). Queue-depth triggers may not be meaningful for stateful actors since work distribution depends on hash distribution, not queue backlog.

2. **DLQ configuration for shard queues**: Each shard queue needs its own DLQ. The composition should auto-configure DLQs for all pre-provisioned queues. Naming convention: `asya-{ns}-{actor}-{ordinal}-dlq`.

3. **Rolling update strategy**: StatefulSet supports `RollingUpdate` (default, reverse ordinal order) and `OnDelete` (manual). For stateful actors with in-flight state, `OnDelete` may be safer to prevent state loss during upgrades. This should be configurable or have a sensible default.

---

## References

- [Fan-In RFC](rfc-fan-in.md) — Aggregation protocol, RocksDB handler, completeness detection (builds on this RFC)
- [A/B Routing RFC](../a-b-testing/rfc-a-b-routing.md) — `x-asya-route-override` header mechanism
- [Actor Flavors RFC](../actor-flavors/rfc-actor-flavors.md) — `fan-in-rocksdb` flavor, composable presets
- [K8s StatefulSet pod-index](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#stable-network-id) — `apps.kubernetes.io/pod-index` label
- [Design Discussion](discussion-stateful-actors.txt) — Full design discussion transcript
