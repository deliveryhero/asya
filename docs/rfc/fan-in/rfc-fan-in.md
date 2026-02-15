# RFC: Fan-In Aggregation with Sharded Embedded Storage

- **Status**: Draft
- **Date**: 2026-02-13
- **Authors**: Artem Yushkovskiy
- **Bead**: asya-7qh
- **Related**: [Fan-Out RFC](asya-fan-in-fan-out.md), [A/B Routing RFC](../a-b-testing/rfc-a-b-routing.md), [Yield-Only Fan-Out Plan](2026-02-10-yield-only-fanout.md)

## Abstract

This RFC defines the aggregation (fan-in) side of Asya's fan-out/fan-in architecture. It specifies how N parallel sub-agent results are collected, merged, and emitted as a single envelope for pipeline continuation. The design uses **sharded aggregator replicas**, each with an **embedded RocksDB store**, where the fan-out router resolves shard affinity at emission time via modulo hashing and the `x-asya-route-override` header mechanism.

## Motivation

The [fan-out RFC](asya-fan-in-fan-out.md) defines how a fan-out router emits N+1 messages (1 setup + N slices). This RFC answers the question: how does the system collect those N slices back into a single envelope?

The aggregator must:

1. **Accept setup messages** that define expected slice count, result field, and continuation route
2. **Accept slice messages** that carry individual sub-agent results
3. **Detect completeness** when all slices have arrived
4. **Emit a merged envelope** with all results assembled and route pointing to the next actor

### Requirements

- **Horizontal scalability**: A single aggregator replica must not be a bottleneck
- **Durability**: In-flight aggregation state must survive pod restarts
- **Simplicity**: No distributed database, no external coordination service
- **Affinity**: All messages for the same parent_id must reach the same replica

---

## Architecture Overview

```
Fan-out router (generated code)
    │
    │  Computes: shard = rendezvous(parent_id, N)
    │  Stamps:   headers["x-asya-route-override"]["aggregator"] = "aggregator-{shard}"
    │
    ├──► Setup message  ──► aggregator-{shard} queue
    ├──► Slice 0        ──► sub-agent queue ──► aggregator-{shard} queue
    ├──► Slice 1        ──► sub-agent queue ──► aggregator-{shard} queue
    └──► Slice 2        ──► sub-agent queue ──► aggregator-{shard} queue
                                                       │
                                                       ▼
                                              aggregator-{shard}
                                              (StatefulSet replica)
                                              RocksDB local store
                                                       │
                                              Completeness detected
                                                       │
                                                       ▼
                                              Emit merged envelope
                                              to continuation actor
```

### Key Properties

- **Route stays abstract**: Compiled routes say `"aggregator"`, not `"aggregator-2"`. Shard resolution happens via `x-asya-route-override` headers at emission time.
- **Sidecar stays simple**: The sidecar performs a dictionary lookup on the override header (as defined in the [A/B routing RFC](../a-b-testing/rfc-a-b-routing.md)). No sharding logic in the sidecar.
- **Fan-out router resolves shards**: The pre-built fan-out crew actor computes the shard via rendezvous hashing and stamps the override header on every emitted message (setup + all slices).
- **Number of shards known to fan-out router at deployment time**: `N` is passed to fan-out router as env variable at deployment time.

---

## Architecture Decision Records

### ADR-1: Embedded RocksDB per Replica (Not Centralized Database)

**Context**: The aggregator needs durable storage for in-flight fan-in state. Options considered:

| Option | Pros | Cons |
|--------|------|------|
| Single PostgreSQL (PVC, 1 replica) | SQL convenience, JSONB support, CDC via LISTEN/NOTIFY | Bottleneck for high-throughput fan-out, single point of failure |
| Distributed PostgreSQL (Citus, CockroachDB) | Horizontal scaling, SQL | Major operational burden, disproportionate to the problem |
| Redis with TTL | Fast, atomic INCR for counting | Adds infrastructure dependency, persistence is optional/complex |
| In-memory per replica | Fastest, simplest | Lost on restart, no durability |
| SQLite per replica | Proven, zero-config, single-file, Python stdlib support | SQL overhead for pure key-value get/put/delete pattern, B-tree less write-optimized than LSM-tree |
| DuckDB per replica | Excellent JSONB-like operations, analytical queries, Python-native | Analytical (OLAP) engine, heavier than needed for OLTP point lookups and atomic updates |
| **Embedded RocksDB per replica** | **Fast writes, durable via PVC, no coordination** | **Manual serialization, no SQL** |

**Decision**: Embedded RocksDB (via `plyvel` Python bindings) per aggregator replica.

**Rationale**:

- **Write-heavy workload**: Aggregation state receives many slice arrivals (writes), checks completeness once (read), and deletes after emission. RocksDB's LSM-tree is optimized for this pattern.
- **Durability without coordination**: Each replica has its own PVC. State survives pod restarts. No cross-replica communication needed.
- **No infrastructure dependency**: RocksDB is an embedded library, not a service to deploy. No PostgreSQL operator, no Redis cluster, no connection pooling.
- **Horizontal scaling**: Add replicas (each with its own RocksDB + PVC). The fan-out router's hash distributes load evenly across shards.
- **Operational simplicity**: No database backups, no replication lag, no connection limits. Each replica is self-contained.

**Consequences**:

- No SQL queries. State access is key-value with manual JSON serialization.
- No cross-replica queries (cannot query all in-flight aggregations globally). Monitoring must aggregate per-replica metrics.
- RocksDB tuning (write buffer size, compaction) may be needed under high load, but defaults are reasonable for most workloads.

### ADR-2: Pre-Built Crew Actor for Fan-Out Shard Resolution

**Context**: The compiled route says `"aggregator"` but messages must reach a specific shard (`"aggregator-2"`). Something must resolve the abstract name to the concrete shard. Options:

| Option | Pros | Cons |
|--------|------|------|
| Standalone shard-resolver actor (separate from fan-out) | Separation of concerns | Extra queue hop per slice (N additional hops per fan-out) |
| Sidecar resolves shards | No extra hop, efficient | Adds specialized logic to the sidecar, violates simplicity principle |
| Compiler-generated inline code | No extra hop, deterministic | Sharding logic coupled to code generation, algorithm changes require recompilation |
| **Pre-built crew actor as fan-out router** | **Reusable, configurable algorithm via env vars, no extra hop** | **Fan-out router is a crew dependency** |

**Decision**: The fan-out router is a **pre-built actor in `asya-crew`** (similar to the experiment `weighted_router` from the [A/B routing RFC](../a-b-testing/rfc-a-b-routing.md)). The Flow DSL compiler generates the route and configuration (env vars), but the fan-out + sharding logic lives in `asya-crew` as a reusable handler.

The fan-out crew actor is configured via environment variables at deployment time:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: fan-out-research-flow
spec:
  image: asya-crew:latest
  handler: asya_crew.fanout.shard_router
  handlerMode: envelope
  env:
    - name: ASYA_FANOUT_ITERATOR
      value: "tasks"                    # payload field to iterate over
    - name: ASYA_FANOUT_RESULT_PATH
      value: "/results"                 # JSON Pointer (RFC 6901) for merged results
    - name: ASYA_FANOUT_TARGET
      value: "aggregator"              # logical actor name to shard
    - name: ASYA_FANOUT_SHARDS
      value: "3"                        # number of aggregator shards
    - name: ASYA_FANOUT_ALGORITHM
      value: "rendezvous"              # sharding algorithm (rendezvous only for now)
```

The compiler's job is to detect list comprehensions in the Flow DSL, determine the iterator field and result field, and generate the AsyncActor manifest with the correct env vars. The actual fan-out logic (N+1 message emission, shard computation, header stamping) is generic and lives in `asya-crew`.

**Available algorithms** (configured via `ASYA_FANOUT_ALGORITHM`):

| Algorithm | Status | Description |
|-----------|--------|-------------|
| `rendezvous` | Available | Rendezvous (HRW): `argmax_i(hash(parent_id, shard_i))`. Minimal redistribution on scale change (~1/N keys move). |
| `consistent` | Planned | Consistent hashing with virtual nodes. Same redistribution properties, different implementation trade-offs. |

Rendezvous is the default and only option for now. It was chosen over simple modulo because the pre-built actor pattern makes algorithm selection a deployment-time concern (env var), and rendezvous provides better scaling properties at negligible implementation cost.

**Rationale**:

- **No extra hop**: The fan-out router IS the sharding actor. It emits N+1 messages with shard-resolved `x-asya-route-override` headers. No separate shard-resolver needed.
- **Reusable**: One crew actor handles all fan-out flows. Different flows configure different iterator fields and shard counts via env vars. No per-flow code generation for the sharding logic.
- **Algorithm is a deployment choice**: Data Scientists write the flow, DevOps/platform team configures the sharding algorithm and shard count at deployment time. No recompilation needed to change algorithms.
- **Leverages existing infrastructure**: The `x-asya-route-override` header from the [A/B routing RFC](../a-b-testing/rfc-a-b-routing.md) provides the resolution mechanism. No new sidecar features needed.
- **Consistent with A/B routing pattern**: Just as A/B testing uses a pre-built `weighted_router` crew actor, fan-out uses a pre-built `shard_router` crew actor. Same pattern, same deployment model.
- **Scale-up safe**: When scaling from N to M shards (M > N), old messages continue to route correctly because the target shard name is baked into the `x-asya-route-override` header at emission time. Old shards still exist. New fan-outs use new shard count.

**Consequences**:

- `asya-crew` becomes a dependency for fan-out flows. This is acceptable since crew actors (happy-end, error-end) are already required infrastructure.
- Adding new sharding algorithms requires updating `asya-crew`, not the compiler or sidecar.
- **Scale-down requires draining**: When reducing shard count, old shards must finish processing in-flight aggregations before removal. See [Open Questions](#open-questions).

### ADR-3: Rendezvous Hashing as Default Algorithm

**Context**: The pre-built fan-out crew actor needs a deterministic function mapping `parent_id` to a shard index. Since the algorithm is now a deployment-time env var (not compiled-in), the choice should favor correctness under scaling over raw simplicity. Three algorithms were considered:

| Algorithm | How it works | Redistribution on scale (N to N+1) | Complexity |
|-----------|-------------|-------------------------------------|------------|
| `hash(key) % N` | Direct modulo of hash output | All keys redistribute (~100%) | Trivial |
| Consistent hashing | Keys and nodes placed on a hash ring; key maps to nearest node clockwise. Virtual nodes (vnodes) improve balance. | ~1/N keys redistribute | Moderate (ring structure, vnodes for uniformity) |
| Rendezvous (HRW) | For each key, compute `hash(key, node_i)` for all nodes; pick the node with highest score. | ~1/N keys redistribute | Simple (argmax of hashes, no ring) |

Both consistent hashing and rendezvous solve the same problem: minimizing key redistribution when the node count changes. Consistent hashing uses a ring with virtual nodes; rendezvous computes a score per node and picks the max. Rendezvous is simpler (no ring, no vnodes) and produces more uniform distribution without tuning, but requires evaluating all N nodes per lookup (O(N) vs O(log N) for ring lookup).

**Decision**: Rendezvous (HRW) as the default and initial algorithm.

**Rationale**:

- **Negligible implementation cost**: Rendezvous is ~10 lines of Python (`argmax(hash(key, shard_i) for i in range(N))`). No ring, no vnodes, no state.
- **Better scaling properties**: When N changes, only ~1/N keys move vs ~100% for modulo. While shard targets are baked into messages at emission time (in-flight fan-outs are unaffected regardless), rendezvous provides smoother behavior for long-running workloads during shard count transitions.
- **Uniform distribution without tuning**: Modulo depends on the hash function's lower bits; consistent hashing needs vnodes for balance. Rendezvous is naturally uniform.
- **O(N) is fine**: N is the shard count (typically 3-20), not the message count. Evaluating `hash(parent_id, shard_i)` for 20 shards is sub-microsecond.

**Why not modulo**: Modulo is simpler but redistributes all keys on scale change. Since algorithm selection is a deployment-time env var (not compiled-in), there is no reason to default to the weaker option. The pre-built actor absorbs the implementation complexity.

**Why not consistent hashing (yet)**: Rendezvous achieves the same redistribution properties with less code and no tuning (vnodes). Consistent hashing will be added as a second option if use cases emerge that benefit from O(log N) lookup (very high shard counts).

**Consequences**:

- In-flight fan-outs are unaffected by shard count changes (destinations already resolved in `x-asya-route-override`). New fan-outs use the new N.
- Scale-up is safe. Scale-down requires draining old shards (TODO: another RFC once this is implemented).

### ADR-4: Hashing Algorithm Selection

**Context**: The sharding algorithms require a hash function that produces uniform distribution over parent_id strings.

**Decision**: Use `xxhash` (xxHash64) via the `xxhash` Python package.

**Rationale**:

- **Speed**: xxHash64 is one of the fastest non-cryptographic hash functions (~30 GB/s on modern CPUs). For a single parent_id string, hashing is effectively free.
- **Uniform distribution**: xxHash64 has excellent avalanche properties and produces uniform distribution across the output space.
- **Deterministic**: Same input always produces the same output. No salt or seed needed for this use case.
- **No cryptographic overhead**: Cryptographic hashes (SHA-256, MD5) are unnecessarily slow. The aggregator does not need collision resistance -- it needs uniform distribution for load balancing.
- **Lightweight dependency**: The `xxhash` package is a thin C binding with no transitive dependencies.

**Alternatives**:

- `hashlib.md5`: Works but 5-10x slower than xxHash. No benefit from cryptographic properties.
- `hash()` builtin: Randomized per process (PYTHONHASHSEED). Not deterministic across replicas or restarts.
- `hashlib.sha256`: Slowest option, no benefit.
- FNV-1a: Good alternative but xxHash has better distribution and speed.

**Usage in pre-built crew actor**:

```python
import os
import xxhash

_SHARD_COUNT = int(os.environ["ASYA_FANOUT_SHARDS"])
_TARGET = os.environ["ASYA_FANOUT_TARGET"]


def _rendezvous_shard(parent_id: str) -> str:
    """Rendezvous (HRW): pick shard with highest hash score."""
    best_shard = 0
    best_score = -1
    for i in range(_SHARD_COUNT):
        score = xxhash.xxh64_intdigest(f"{parent_id}:{i}".encode())
        if score > best_score:
            best_score = score
            best_shard = i
    return f"{_TARGET}-{best_shard}"
```

---

## Fan-In Protocol

### Addressed Fan-In

The `x-asya-fanin` header is **transient**: it exists only on messages between the fan-out router and the aggregator (setup and slice messages). The fan-out router stamps it at emission time; the aggregator reads it and strips it from the merged envelope before emitting to the continuation actor. Outside of the fan-out/fan-in segment of the pipeline, this header is not present.

The header includes an `actor` field that identifies the target aggregator actor. The aggregator checks `x-asya-fanin.actor == ASYA_ACTOR_NAME` to confirm the header is addressed to it. The storage key is `(parent_id, actor)`.

For sequential fan-outs in the same flow, each fan-out produces a new envelope with a new ID, so `parent_id` is naturally different and the same aggregator actor can serve both:

```python
def multi_fanout(p: dict) -> dict:
    # Fan-out 1: parent_id = original envelope ID
    p["research"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
    # Fan-out 2: parent_id = merged envelope ID from fan-out 1
    p["reviews"] = [review_agent(p["research"][i]) for i in range(len(p["research"]))]
    return p
```

### Setup Message

The fan-out router emits a setup message to the aggregator shard. This message carries the full parent payload, the slice count, the result path, and the continuation route (pre-incremented past the aggregator).

```json
{
  "id": "setup-xyz",
  "parent_id": "envelope-xyz",
  "route": {
    "actors": ["start", "fan_out", "aggregator", "post_process"],
    "current": 2
  },
  "headers": {
    "x-asya-route-override": {"aggregator": "aggregator-2"},
    "x-asya-fanin": {
      "actor": "aggregator",
      "type": "setup",
      "slice_count": 5,
      "result_path": "/results"
    }
  },
  "payload": {
    "original_field": "preserved"
  }
}
```

### Slice Message

Each slice message carries the sub-agent's result and its position in the result array.

```json
{
  "id": "slice-xyz-0",
  "parent_id": "envelope-xyz",
  "route": {
    "actors": ["sub_agent", "aggregator"],
    "current": 1
  },
  "headers": {
    "x-asya-route-override": {"aggregator": "aggregator-2"},
    "x-asya-fanin": {
      "actor": "aggregator",
      "type": "slice",
      "slice_index": 0,
      "slice_count": 5
    }
  },
  "payload": {
    "result": "sub-agent output for slice 0"
  }
}
```

### Fan-In Metadata Header

Fan-in coordination uses `x-asya-fanin` header (separate from `x-asya-route-override`):

| Field | Setup | Slice | Description |
|-------|-------|-------|-------------|
| `actor` | actor name | actor name | Target aggregator actor. Aggregator checks this matches its `ASYA_ACTOR_NAME`. |
| `type` | `"setup"` | `"slice"` | Discriminator |
| `slice_count` | N | N | Total number of slices |
| `result_path` | JSON Pointer | - | RFC 6901 path where merged results are placed (e.g., `/results`) |
| `slice_index` | - | 0..N-1 | Position of this slice in the result array (mirrors `route.current` naming) |

---

## Aggregator Actor Design

### Handler Implementation

The aggregator is a crew actor running in envelope mode. It persists state to a local RocksDB instance.

```python
import json
import os

import jsonpointer
import plyvel

_DB_PATH = os.environ.get("ASYA_AGGREGATOR_DB_PATH", "/data/aggregator")
_db = plyvel.DB(_DB_PATH, create_if_missing=True)


def aggregator(envelope: dict) -> dict | None:
    parent_id = envelope.get("parent_id") or envelope["id"]
    fanin = envelope["headers"]["x-asya-fanin"]

    # Composite key: (parent_id, actor) supports multiple fan-ins per flow
    key = f"{parent_id}:{fanin['actor']}".encode("utf-8")

    if fanin["type"] == "setup":
        _handle_setup(key, envelope, fanin)
    elif fanin["type"] == "slice":
        _handle_slice(key, envelope, fanin)

    # Check completeness: slice_count slices + 1 setup
    state = _load_state(key)
    if state and state["received_count"] == state["slice_count"] + 1:
        merged = _build_merged_envelope(state)
        _db.delete(key)
        return merged

    return None  # Not complete yet, ack and wait


def _handle_setup(key: bytes, envelope: dict, fanin: dict):
    route = envelope["route"].copy()
    route["current"] += 1  # Pre-increment for continuation

    state = _load_state(key) or {
        "route": route,
        "payload": envelope["payload"],
        "headers": {k: v for k, v in envelope.get("headers", {}).items()
                    if not k.startswith("x-asya-fanin")},
        "slice_count": fanin["slice_count"],
        "result_path": fanin["result_path"],
        "results": [None] * fanin["slice_count"],
        "received_count": 0,
    }
    state["received_count"] += 1
    _save_state(key, state)


def _handle_slice(key: bytes, envelope: dict, fanin: dict):
    state = _load_state(key)
    if state is None:
        # Slice arrived before setup (race condition)
        # Create partial state, setup will fill in the rest
        state = {
            "route": None,
            "payload": None,
            "headers": None,
            "slice_count": fanin["slice_count"],
            "result_path": None,
            "results": [None] * fanin["slice_count"],
            "received_count": 0,
        }

    state["results"][fanin["slice_index"]] = envelope["payload"]
    state["received_count"] += 1
    _save_state(key, state)


def _build_merged_envelope(state: dict) -> dict:
    payload = state["payload"].copy()
    jsonpointer.set_pointer(payload, state["result_path"], state["results"])

    envelope = {
        "route": state["route"],
        "payload": payload,
    }
    if state["headers"]:
        envelope["headers"] = state["headers"]
    return envelope


def _load_state(key: bytes) -> dict | None:
    data = _db.get(key)
    if data is None:
        return None
    return json.loads(data)


def _save_state(key: bytes, state: dict):
    _db.put(key, json.dumps(state).encode("utf-8"))
```

### Completeness Detection

The aggregator checks completeness **synchronously after every write** (both setup and slice). When `received_count == slice_count + 1` (N slices + 1 setup), the aggregator:

1. Builds the merged envelope from stored state
2. Deletes the state from RocksDB
3. Returns the merged envelope (sidecar routes to continuation actor)

No CDC process needed. No polling. No LISTEN/NOTIFY. The aggregator itself is the completeness detector.

**Why this works**: Every message (setup or slice) triggers a completeness check. The last message to arrive (whichever it is) will find `received_count == slice_count + 1` and emit. All other messages return `None` (ack, no routing).

**Multiple fan-ins**: The composite storage key `(parent_id, actor)` ensures that multiple fan-in operations are tracked independently. For sequential fan-outs in the same flow, each produces a new envelope with a new ID, so `parent_id` is naturally different even when targeting the same aggregator actor.

### Race Condition: Slice Before Setup

Slices can arrive before the setup message (sub-agents may complete before the setup message traverses the queue). The aggregator handles this by creating a partial state entry on first slice arrival. When the setup message eventually arrives, it fills in the missing fields (route, payload, result_path).

The completeness condition (`received_count == slice_count + 1`) ensures that emission only happens after both setup AND all slices have been processed.

### Ordering Guarantees

- Slice results are placed at `results[slice_index]`, maintaining order regardless of arrival order.
- The `slice_index` is assigned by the fan-out router at emission time and carried in the `x-asya-fanin` header.

---

## Deployment

### StatefulSet Configuration

Each aggregator shard is a StatefulSet replica with a PVC for RocksDB storage:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator
spec:
  image: asya-crew:latest
  handler: asya_crew.aggregator.aggregator
  handlerMode: envelope
  transport: sqs
  workloadType: StatefulSet
  replicas: 3
  volumeClaimTemplates:
    - metadata:
        name: aggregator-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
  env:
    - name: ASYA_AGGREGATOR_DB_PATH
      value: /data/aggregator/db
  volumeMounts:
    - name: aggregator-data
      mountPath: /data/aggregator
```

### Queue Naming

Each StatefulSet replica gets its own queue following the pattern:

- `asya-{namespace}-aggregator-0`
- `asya-{namespace}-aggregator-1`
- `asya-{namespace}-aggregator-2`

This requires the Crossplane composition (or operator) to create N queues when `workloadType: StatefulSet` and `replicas: N`. Each pod's sidecar consumes from its own queue, identified by the pod's ordinal index.

### Fan-Out Router Configuration

The fan-out router uses the pre-built `asya_crew.fanout.shard_router` handler, configured via environment variables:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: fan-out-research-flow
spec:
  image: asya-crew:latest
  handler: asya_crew.fanout.shard_router
  handlerMode: envelope
  env:
    - name: ASYA_FANOUT_ITERATOR
      value: "tasks"
    - name: ASYA_FANOUT_RESULT_FIELD
      value: "results"
    - name: ASYA_FANOUT_TARGET
      value: "aggregator"
    - name: ASYA_FANOUT_SHARDS
      value: "3"
    - name: ASYA_FANOUT_ALGORITHM
      value: "rendezvous"
```

---

## Scaling Behavior

### Scale Up (N to M, M > N)

1. Deploy M aggregator replicas (new shards get new queues and PVCs)
2. Redeploy fan-out router with `ASYA_FANOUT_SHARDS=M`
3. In-flight fan-outs continue correctly: their messages already carry `x-asya-route-override` targeting shards 0..(N-1), which still exist
4. New fan-outs distribute across shards 0..(M-1)

**Safe**: No data loss, no coordination needed.

### Scale Down (N to M, M < N)

Scaling down requires draining shards M..(N-1) before removal:

1. Redeploy fan-out router with `ASYA_FANOUT_SHARDS=M` (new fan-outs only target shards 0..(M-1))
2. Wait for shards M..(N-1) to complete all in-flight aggregations
3. Verify queues for shards M..(N-1) are empty
4. Remove StatefulSet replicas M..(N-1) and their PVCs

**Requires draining**: See [Open Questions](#open-questions) for tooling.

### Fan-Out Atomicity

If the fan-out router crashes mid-emission (after emitting some messages but not all), a partial fan-out occurs. The aggregator will wait indefinitely for missing slices.

**Mitigation**: TTL-based cleanup. Aggregation state older than a configurable timeout (e.g., 1 hour) is considered stale and deleted. The original message is nacked (if transport supports it) or sent to error-end.

This is an orthogonal concern to sharding and applies regardless of the number of shards.

---

## Integration with A/B Routing

The fan-in sharding mechanism reuses the `x-asya-route-override` header from the [A/B routing RFC](../a-b-testing/rfc-a-b-routing.md). This is explicitly listed as Use Case 4 in that RFC.

The integration is clean:

- Fan-out router stamps `x-asya-route-override: {"aggregator": "aggregator-2"}`
- Sidecar at routing time performs a dictionary lookup (existing Layer 1 mechanism)
- Route still says `"aggregator"` (business logic preserved)
- `x-asya-route-resolved` header provides audit trail

A/B testing and fan-in sharding can coexist in the same pipeline. For example, a pipeline could A/B test the sub-agent AND shard the aggregator:

```json
{
  "x-asya-route-override": {
    "research_agent": "research_agent_v2",
    "aggregator": "aggregator-1"
  }
}
```

---

## Open Questions

### 1. Configuration Mechanism for Shard Count

How does the fan-out router learn `ASYA_FANOUT_SHARDS`? Options:

- **Simple env var**: Set on the fan-out router's AsyncActor spec. Requires redeployment to change.
- **ConfigMap**: Fan-out router reads from a ConfigMap. Can be updated without redeployment (if router watches for changes).
- **Crossplane EnvironmentConfig**: Crossplane injects shard count from the aggregator's replica count into the fan-out router's environment. Declarative, but couples Crossplane resources.

Decision deferred until the Crossplane/operator deployment model for StatefulSet actors is finalized (depends on asya-altb).

### 2. Draining Workflow for Scale-Down

When scaling down, old shards must complete in-flight work. Tooling options:

- **CLI command**: `asya aggregator drain --shard 3 --timeout 10m` -- waits for shard to empty, then reports ready for removal.
- **Operator-managed**: Operator watches StatefulSet replica count changes and automatically drains before removing pods.
- **Manual**: User monitors queue depth and RocksDB key count, removes shards when both are zero.

Decision deferred. The first implementation should document the manual process.

### 3. TTL and Stale State Cleanup

Aggregation state for incomplete fan-outs (partial failures) should be cleaned up. Options:

- **Background goroutine/thread** in the aggregator that scans RocksDB for entries older than TTL and deletes them.
- **On-read check**: Every state access checks timestamp and deletes if stale.
- **External CronJob**: Periodic cleanup process.

The background thread approach is simplest and keeps the cleanup self-contained within the aggregator.

### 4. Monitoring and Observability

Per-replica metrics needed:

- `asya_aggregator_active_fanouts` (gauge): Number of in-flight aggregations
- `asya_aggregator_slices_received_total` (counter): Total slices received
- `asya_aggregator_completions_total` (counter): Total completed aggregations
- `asya_aggregator_stale_cleanups_total` (counter): Stale entries cleaned up
- `asya_aggregator_rocksdb_size_bytes` (gauge): RocksDB on-disk size

### 5. Header Syntax Constraints for Transport Compatibility

Asya headers (`x-asya-*`) currently live inside the envelope JSON's `headers` field. If headers are promoted to transport-level metadata (for routing decisions without full message deserialization), they must respect the lowest common denominator across transports:

| Constraint | Most restrictive | Limit |
|---|---|---|
| Max attributes per message | SQS | 10 |
| Max single value size | Pub/Sub | 1024 bytes |
| Value types | Pub/Sub | String only |
| Total metadata size | Azure Service Bus | 64 KB |
| Key characters | SQS | Alphanumeric, `_`, `-`, `.` |

**Current `x-asya-*` header budget** (worst case: all features active):

| Header | Set by | Size estimate |
|---|---|---|
| `x-asya-route-override` | Router actors | Small dict: `{"model": "model-v2"}` (~50 bytes) |
| `x-asya-route-resolved` | Sidecar | Audit trail dict (~100 bytes) |
| `x-asya-fanin` | Fan-out router | `{"actor": "...", "type": "...", ...}` (~100 bytes) |
| `x-asya-experiment` | Experiment router | String (~30 bytes) |
| `x-asya-variant` | Experiment router | String (~30 bytes) |
| | | **5 of 10 SQS slots** |

This leaves 5 slots for user-defined headers (`trace_id`, `priority`, etc.).

**Design constraints for this RFC**:

- `x-asya-fanin` is a single object (not a list) -- a message participates in at most one fan-in at a time
- All values must serialize to JSON strings under 1024 bytes (Pub/Sub limit)
- The `actor` field ensures the aggregator can identify headers addressed to it without consuming additional attribute slots

**Broader question**: A dedicated RFC should define the general header contract -- naming conventions, size budgets, transport promotion rules, and reserved vs user-defined header namespaces. This is out of scope for the fan-in RFC but noted here as a dependency.

### 6. Nested Fan-Out

Can a sub-agent itself fan-out? This creates a tree of aggregations. The current design supports this because:

- Each fan-out generates a unique `parent_id`
- Nested fan-outs produce different `parent_id` values
- Each aggregation is independent

However, the continuation route for a nested fan-out must correctly point back to the outer aggregator. This requires the inner fan-out router to preserve the outer route context. Design deferred until the use case is validated.

---

## References

- [Fan-Out RFC](asya-fan-in-fan-out.md) -- Fan-out architecture, N+1 message pattern
- [Yield-Only Fan-Out Plan](2026-02-10-yield-only-fanout.md) -- Streaming wire protocol for generators
- [A/B Routing RFC](../a-b-testing/rfc-a-b-routing.md) -- `x-asya-route-override` header mechanism
- [JSON Pointer (RFC 6901)](https://www.rfc-editor.org/rfc/rfc6901) -- Standard for addressing values within JSON documents
- [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) -- Python implementation of JSON Pointer (zero dependencies)
- [RocksDB](https://rocksdb.org/) -- Embedded key-value store
- [plyvel](https://plyvel.readthedocs.io/) -- Python bindings for LevelDB (RocksDB-compatible API)
- [xxHash](https://xxhash.com/) -- Non-cryptographic hash function
