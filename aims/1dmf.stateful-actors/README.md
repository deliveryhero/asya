---
title: State-Backed Actors
status: open
priority: 2 # medium
type: epic
---

## Summary

This RFC defines how Asya actors access shared state across messages. All Asya actors remain **stateless Deployments** -- there are no StatefulSets, no per-pod queues, no shard affinity. Actors that need state across messages use an **external state store** (a pluggable backing service such as Redis, DynamoDB, or NATS KV). This pattern is called **state-backed actors**.

Fan-in aggregation is the primary use case. Other potential use cases (deduplication, rate limiting, session memory) are addressed by other layers of the architecture or deferred.

---

## Motivation

Asya's current actor model is stateless: each message is processed independently, and no state is shared between messages. This works for single-request processing but breaks for **fan-in aggregation**, where partial results from a fan-out must converge and be assembled into a single output.

The naive solution -- shard affinity via StatefulSets and per-pod queues -- introduces significant complexity: placement directories, shard routing, rebalancing on scale events, and custom controllers. This RFC argues that a simpler approach (externalized state) solves the fan-in problem without any of that complexity.

### Requirements

- **Correctness**: Messages with the same aggregation key must update the same state, regardless of which pod processes them
- **No local state**: Actors remain stateless Deployments with standard KEDA autoscaling
- **No framework changes**: No sidecar, injector, or XRD changes required
- **Pluggable state store**: Users bring their own database (Redis, DynamoDB, NATS KV, etc.)
- **Transport-agnostic**: Works identically with SQS, RabbitMQ, and future transports

---

## Use-Case Analysis

Before designing the solution, we analyzed all potential use cases for cross-message state. Most do not belong in the actor layer.

| Use case | Sharding key | Belongs in | Rationale |
|----------|-------------|------------|-----------|
| **Fan-in aggregation** | `origin_id` | **Actor layer (this RFC)** | Only use case requiring cross-message state in the pipeline |
| Deduplication | `message_id` | Gateway | Gateway already tracks task state; dedup is a gateway concern (idempotency) |
| Per-key rate limiting | `client_id` | Gateway | Rate limiting is an ingress concern, not a pipeline concern |
| Session/conversation memory | `session_id` | External database directly (partially this RFC) | Sessions require unbounded, elastic storage -- far beyond what Asya should manage |
| Time-window batching | `batch_key` | Out of scope | Complex windowing semantics (Flink territory); not an Asya concern |

### Why Fan-In Is the Only Actor-Layer Use Case

**Deduplication and rate limiting** are request-level concerns handled at ingress. The asya-gateway already maintains task state and is the natural place for idempotency checks and rate limits. Moving these into the pipeline would duplicate responsibility.

**Session memory** requires storing unbounded conversation histories (potentially megabytes per session) across millions of concurrent sessions. This needs an elastic, HA database (DynamoDB, PostgreSQL, Redis Cluster) that the application team manages directly. It is not Asya's job to abstract session storage -- the handler simply connects to whatever database the team already uses.

**Time-window batching** requires timer-based triggers, window semantics, and late-arrival handling. This is stream processing (Apache Flink, Spark Streaming), not message passing. Asya should not reinvent stream processing primitives.

**Fan-in aggregation** is different: it has bounded state (finite number of partial results per origin), bounded lifetime (seconds to minutes), and a clear completion condition (all partials received). It is a natural fit for a lightweight crew actor with pluggable state.

---

## Proposed Solution: State-Backed Actors

### Core Concept

A state-backed actor is a **standard stateless Deployment** that reads and writes shared state via an **external state store**. Any pod can process any message because state is not local -- it lives in the backing service.

```
        aggregator queue (single shared queue)
                |
    +-----------+-----------+
    |           |           |
  Pod-0      Pod-1       Pod-2      (stateless Deployment, KEDA-scaled)
    |           |           |
    +-----+-----+-----+----+
          |
    External State Store
    (Redis / DynamoDB / NATS KV / ...)
```

### Properties

- **No StatefulSet**: Plain Deployment with competing consumers
- **No per-pod queues**: Single shared queue per actor
- **No shard affinity**: Any pod handles any message
- **No placement directory**: No routing logic needed
- **Standard autoscaling**: KEDA scales on queue depth, same as any stateless actor
- **No sidecar changes**: The sidecar is unaware of state -- the handler manages it
- **No XRD changes**: State store connection is configured via env vars
- **No composition changes**: The actor deploys like any other stateless actor

### Concurrency Model

Multiple pods may process messages for the same aggregation key simultaneously. The state store provides atomicity via **compare-and-swap (CAS)**:

1. Pod reads current state for key (gets value + revision)
2. Pod merges its partial result into the state
3. Pod writes updated state with revision check (CAS)
4. If another pod updated first (revision mismatch), retry from step 1

This is the standard optimistic concurrency pattern used by every distributed database.

### State Store Interface

The fan-in crew actor uses a pluggable `StateStore` interface. The backend is selected via environment variables.

```python
class StateStore(ABC):
    """Interface for fan-in state storage backends."""

    @abstractmethod
    async def get(self, key: str) -> Optional[tuple[bytes, Any]]:
        """Read state for key. Returns (value, revision) or None."""

    @abstractmethod
    async def create(self, key: str, value: bytes, ttl: Optional[int] = None) -> bool:
        """Atomically create key if not exists. Returns True on success."""

    @abstractmethod
    async def update(self, key: str, value: bytes, revision: Any) -> bool:
        """CAS update: write value only if revision matches. Returns True on success."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete key (cleanup after completion)."""
```

Implementations: `RedisStateStore`, `DynamoDBStateStore`, `NatsKvStateStore`, etc.

### Configuration

The state store is configured via env vars on the actor (or via flavor defaults):

```yaml
env:
  - name: ASYA_FANIN_STORE
    value: "redis"  # or: dynamodb, nats, ...
  - name: ASYA_FANIN_STORE_URL
    value: "redis://redis:6379"
```

### Fan-In as a Crew Actor

Fan-in is implemented as a new `x-fanin` crew actor in `asya-crew`, alongside `x-sink` and `x-sump`. The fan-in handler, state store interface, and backend implementations all live in `asya-crew`.

The fan-in protocol (message format, completeness detection, merge strategy) is defined in a separate RFC. This RFC only establishes the architectural pattern.

---

## Architecture Decision Records

### ADR-1: Stateless Deployment + External State vs. StatefulSet + Local State

**Context**: Actors that need cross-message state (e.g., fan-in aggregation) could either maintain state locally (StatefulSet with per-pod storage) or externalize state to a shared database.

| Approach | Scaling | Complexity | Access latency | Failure mode |
|----------|---------|------------|----------------|--------------|
| **StatefulSet + local RocksDB** | Complex (shard rebalancing, placement directory, N per-pod queues) | High (sidecar changes, injector changes, XRD changes, new composition logic) | Sub-ms (local disk) | Pod failure = state locked on PVC until pod restarts |
| **Deployment + external state store** | Standard KEDA (no rebalancing) | Low (no framework changes, handler-level concern) | ~1ms (Redis), ~5ms (DynamoDB) | Pod failure = message returns to queue, another pod continues |

**Decision**: Stateless Deployment with external state store.

**Rationale**: For Asya's primary workload (AI pipelines), each sub-agent takes seconds to process a message. The ~1-5ms overhead of an external state store is negligible compared to seconds of LLM inference. The architectural simplicity is worth far more than sub-millisecond local access:

- No sidecar changes
- No injector changes
- No XRD changes
- No composition changes
- No StatefulSet controller interactions
- No shard routing or placement logic
- Standard KEDA autoscaling
- Graceful failure handling (message returns to queue, any pod retries)

**Consequence**: Actors that genuinely need local disk state (e.g., high-throughput streaming with sub-ms latency requirements) cannot use this pattern. Such workloads are out of scope for Asya's actor model and should use purpose-built stream processing tools (Kafka Streams, Flink).

### ADR-2: Against Shard Affinity for Fan-In

**Context**: The original design used shard affinity (StatefulSet with per-pod queues) so that all partial results for a given key would land on the same pod. This required a placement directory to map keys to shards.

We explored multiple shard routing approaches:

| Approach | How it works | Problem |
|----------|-------------|---------|
| **Static hashing** (rendezvous / consistent hash) | Sender computes `hash(key) % N` | Scale events (N changes) remap keys -- partial results split across old and new shards |
| **Stamped-N** (sender stamps shard count into message) | Gateway stamps N at send time | Gateway must know N reliably; ConfigMap sync lag makes this unreliable |
| **Virtual shards** (fixed V virtual, variable N physical) | `hash(key) % V`, V mapped to N | Scale events require reassigning virtual shards and migrating state |
| **Semi-stateful router** (placement directory in embedded KV) | Router stores `key -> shard` in RocksDB | Router is SPOF; HA requires Raft consensus (building a mini-database) |

All shard affinity approaches suffer from the same fundamental problem: **scale events require coordinated state migration or routing reconfiguration**. This is the core challenge of any sharded stateful system (Kafka, Vitess, CockroachDB, Akka Cluster Sharding all solve it, but with significant infrastructure complexity).

**Decision**: No shard affinity. Use external state store with CAS concurrency instead.

**Rationale**: The external state store eliminates the routing problem entirely. Any pod can process any message. Scale events require no coordination. The CAS concurrency model handles concurrent access correctly without shard boundaries.

### ADR-3: Against Building a Placement Directory

**Context**: To make shard affinity work with dynamic scaling, we explored building a placement directory (a mapping from key to shard index) that persists across scale events. This is the pattern used by Dapr (Placement Service), Vitess (Lookup VIndex), and Akka (Shard Coordinator).

We evaluated multiple placement store options:

| Store | CNCF Status | Embeddable? | Consistency | Min Pods | Verdict |
|-------|-------------|-------------|-------------|----------|---------|
| Embedded Badger (single-node) | None | Yes (Go) | CP (single writer) | 0 | SPOF -- placement data lost on pod failure |
| Embedded Badger + hashicorp/raft | None | Yes (Go) | CP (Raft) | 0 (embedded) | ~300-500 LoC of custom consensus code |
| NATS JetStream KV | Incubating | Yes (Go) | CP (Raft) | 1-3 | Raft-limited throughput (~1-5K writes/sec) |
| Olric (distributed Go KV) | None | Yes (Go) | AP (best-effort) | 0 (embedded) | AP semantics break placement correctness |
| Redis/Valkey | None (LF) | No | AP (async replication) | 1-4 | Adds infra dependency; SETNX provides CAS |
| etcd | Graduated | Yes (heavy) | CP (Raft) | 3 | Overkill for routing table; heavy binary |
| TiKV | Graduated | No | CP (Raft) | 6 | Massive overkill (petabyte-scale system) |

**Decision**: Do not build a placement directory. The external state store approach eliminates the need for one.

**Rationale**: A placement directory adds a distributed consensus system (Raft or equivalent) to the architecture. Whether embedded (hashicorp/raft) or external (NATS KV, etcd), it introduces operational complexity and failure modes. Since the external state store approach avoids shard affinity entirely, no placement directory is needed.

**Consequence**: If a future workload genuinely requires shard affinity (e.g., per-pod GPU state that cannot be externalized), this decision can be revisited. But fan-in aggregation does not require it.

### ADR-4: Against Embedding Consensus in Actors

**Context**: For HA placement directories, we considered embedding Raft consensus (via hashicorp/raft) directly in the router actor. This would give CP consistency with zero external dependencies.

**Decision**: Do not embed consensus protocols in actors.

**Rationale**: Embedding Raft in an actor means building and maintaining a distributed database inside a message handler. This is:

- **Wrong abstraction level**: Actors process messages; they should not be databases
- **Hard to operate**: Raft requires stable pod identity, peer discovery, and careful failure handling
- **Hard to test**: Consensus protocols need partition testing, leader election testing, and log compaction testing
- **Duplicative**: Proven distributed KV stores (Redis, DynamoDB, NATS) already solve this problem

If an actor needs consistent shared state, it should use an external database purpose-built for that job.

### ADR-5: Pluggable State Store, Not a Prescribed Database

**Context**: Should Asya prescribe a specific state store (e.g., NATS KV) or let users bring their own?

| Option | Pros | Cons |
|--------|------|------|
| Prescribe NATS KV | One default, CNCF-backed | Raft-limited throughput (~1-5K writes/sec); overkill for small workloads; not enough for large ones |
| Prescribe Redis | Universal, fast (~100K ops/sec) | Not CNCF; adds infra dependency |
| **Pluggable interface** | **Users bring existing infra; scales from dev to production** | **Multiple backends to maintain** |

**Decision**: Pluggable `StateStore` interface with multiple backend implementations.

**Rationale**: Different deployments have different infrastructure. AWS-native teams have DynamoDB. Teams with existing Redis can reuse it. Small deployments can use NATS KV. The fan-in crew actor should not force an infrastructure choice.

The `StateStore` interface is minimal (get, create, update, delete) and maps naturally to any KV store or database that supports atomic operations.

**Scaling characteristics of evaluated backends:**

| Backend | Write throughput | Horizontal scaling | Best for |
|---------|-----------------|-------------------|----------|
| NATS KV | ~1-5K ops/s (Raft-limited, single leader) | Not horizontally shardable | Small scale (< 1K concurrent fan-ins) |
| Redis/Valkey | ~100K ops/s (single thread) | Redis Cluster (auto-sharding) | Medium to large scale |
| DynamoDB | Virtually unlimited (on-demand) | Automatic (managed) | Large scale, AWS-native |

### ADR-6: Fan-In as Crew Actor, Not Framework Primitive

**Context**: Should fan-in be a framework-level primitive (with XRD fields, composition logic, and sidecar support) or an application-level crew actor?

| Option | Framework changes | Flexibility |
|--------|------------------|-------------|
| Framework primitive (`spec.stateful`) | Sidecar, injector, XRD, composition changes | Locked to framework's opinionated design |
| **Crew actor (`x-fanin`)** | **None** | **Pluggable state store, customizable merge logic** |

**Decision**: Implement fan-in as a crew actor in `asya-crew`.

**Rationale**: A crew actor requires zero framework changes. The fan-in handler, state store interface, and backend implementations all live in `asya-crew` as application code. Users configure the state store via env vars or flavors. The sidecar, injector, XRD, and composition remain unchanged.

This also means fan-in can evolve independently of the framework release cycle.

### ADR-7: All Actors Remain Stateless Deployments

**Context**: The original RFC proposed adding StatefulSet support to the AsyncActor XRD. This would require conditional logic in compositions, injector changes for pod-index detection, sidecar changes for per-pod queue names, and KEDA configuration for StatefulSet scaling.

**Decision**: Do not add StatefulSet support. All actors remain stateless Deployments.

**Rationale**: The state-backed actor pattern eliminates the need for StatefulSets. With externalized state:

- No pod needs stable identity
- No pod needs persistent local storage
- No pod needs a dedicated queue
- Scaling is standard (add/remove pods, no rebalancing)
- Pod failure is graceful (message returns to queue, any pod retries)

This keeps the framework simple: one workload type (Deployment), one queue model (shared queue with competing consumers), one scaling model (KEDA on queue depth).

**Consequence**: The `spec.stateful` XRD field from the original RFC is not needed. The `volumeClaimTemplates`, `preCreateQueues`, and pod-index injection features are also not needed.

### ADR-8: Use Cases Routed to Appropriate Layers

**Context**: The original RFC listed five stateful use cases (fan-in, session memory, deduplication, rate limiting, time-window batching) as motivations for a general-purpose stateful actor primitive.

**Decision**: Route each use case to the most appropriate layer.

| Use case | Layer | Rationale |
|----------|-------|-----------|
| Fan-in aggregation | Actor (`x-fanin` crew actor) | Bounded state, bounded lifetime, clear completion condition |
| Deduplication | Gateway | Already tracks task state; idempotency is an ingress concern |
| Rate limiting | Gateway | Rate limiting is an ingress/API concern, not a pipeline concern |
| Session memory | Application database (user-managed) | Unbounded state, requires elastic storage; not an Asya concern |
| Time-window batching | Out of scope | Stream processing semantics (Flink territory) |

**Rationale**: A general-purpose stateful actor primitive would be over-engineering. Fan-in is the only use case that fits naturally in the actor pipeline. The others are either gateway concerns, application-level database concerns, or stream processing concerns that Asya should not attempt to solve.

---

## Impact on Existing Architecture

### No Changes Required

| Component | Change |
|-----------|--------|
| asya-sidecar | None |
| asya-injector | None |
| asya-runtime | None |
| asya-gateway | None (dedup/rate-limiting are future gateway features) |
| Crossplane XRD | None |
| Crossplane Compositions | None |
| Helm charts | None |
| KEDA configuration | None |

### New Components

| Component | Description |
|-----------|-------------|
| `asya-crew/x-fanin` | Fan-in aggregation handler with pluggable state store |
| `asya-crew/state_store/` | `StateStore` interface and backend implementations |
| `fan-in` flavor | Preconfigured flavor for fan-in actors |

---

## Example: Fan-In Pipeline (Conceptual)

The fan-in protocol (message format, completeness detection, merge strategy) is defined in a separate RFC. This example shows only the deployment topology.

```yaml
# 1. Fan-out router (stateless, splits work)
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
---
# 2. Sub-agent (stateless, does the work)
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
# 3. Aggregator (state-backed, assembles results)
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator
spec:
  actor: aggregator
  transport: sqs
  flavors: [fan-in]
  workload:
    template:
      spec:
        containers:
          - name: asya-runtime
            image: asya-crew:latest
            env:
              - name: ASYA_HANDLER
                value: "asya_crew.fanin.handle"
              - name: ASYA_HANDLER_MODE
                value: "envelope"
              - name: ASYA_FANIN_STORE
                value: "redis"
              - name: ASYA_FANIN_STORE_URL
                value: "redis://redis:6379"
```

**Message flow:**
1. Request arrives at `fanout-research` queue
2. Fan-out router splits into N sub-tasks, stamps each with `origin_id` and `expected_count`
3. Sub-agents process independently (competing consumers, 5 pods)
4. Sub-agent results route to `aggregator` queue
5. Any aggregator pod reads partial state from Redis, merges new result, CAS-writes back
6. When all partials received, aggregator emits merged result to next step (or x-sink)

Key difference from the original RFC: the aggregator is a **standard Deployment** with a single shared queue. No StatefulSet, no per-pod queues, no shard routing. Redis (or DynamoDB, NATS KV, etc.) provides the shared state.

---

## Open Questions

1. **Fan-in protocol**: How does the fan-out router stamp messages with `origin_id` and `expected_count`? How does the aggregator detect completeness? How is the merge performed? Defined in a separate RFC.

2. **State store lifecycle**: Who provisions the state store (Redis, DynamoDB, etc.)? Options: user-managed (BYO), Crossplane-managed (auto-provision), or Helm-chart-managed (deploy alongside Asya).

3. **TTL and cleanup**: What happens if a fan-in never completes (sub-agent failure, message loss)? The state store should have TTL-based cleanup to prevent unbounded growth. The TTL value depends on the workload.

4. **Large payloads**: If partial results exceed the state store's value size limit (e.g., 1MB for NATS KV, 512MB for Redis), payloads should be stored in S3/MinIO with pointers in the state store. The `StateStore` interface may need a companion `PayloadStore` for this pattern.

5. **Retry semantics**: When a CAS update fails due to contention (multiple pods updating the same key), the handler retries internally. When the state store is unavailable (e.g., Redis down), the handler returns an error, triggering the sidecar's retry logic (exponential backoff per the resiliency RFC). If all retries exhaust, the message routes to x-sump.

---

## References

- Fan-In Protocol RFC (TBD) -- Message format, completeness detection, merge strategy
- A/B Routing RFC (epic 1crb) -- `x-asya-route-override` header mechanism (not needed for state-backed approach but remains available for other use cases)
- Resiliency RFC (#181) -- Sidecar retry logic with exponential backoff
- Actor Flavors RFC -- `fan-in` flavor, composable presets
- Design discussion transcript (archived) -- Full exploration of shard affinity, placement directories, NATS KV, and the decision to use externalized state
