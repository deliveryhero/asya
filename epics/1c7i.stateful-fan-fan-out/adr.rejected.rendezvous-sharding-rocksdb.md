---
title: "ADR: Rejected — Sharded Aggregators with Embedded RocksDB and Rendezvous Hashing"
status: rejected
superseded_by: "rfc.md (actualized: S3 split-key, extensible flavors)"
date: 2025-02-23
---

# ADR: Sharded Aggregators with Embedded RocksDB

## Status

**Rejected** in favor of the extensible flavor architecture (see rfc.md).
Preserved for historical context and future reference if sharded flavors are revisited.

## Context

The original fan-in RFC proposed sharded aggregator replicas, each with an
embedded RocksDB store. The fan-out router resolved shard affinity at emission
time via rendezvous hashing and the `x-asya-route-override` header.

This design was explored before the Semi-Stateful Actors RFC (epic 1dmf)
established the state proxy architecture. Epic 1dmf's ADR-6 (Stateless
Deployment + external state), ADR-7 (Against shard affinity for fan-in),
and ADR-9 (Fan-in as crew actor using state mounts) directly contradict
this approach.

## The Proposed Architecture

```
Fan-out router (generated code)
    |
    |  Reads:    origin_id = message.id
    |  Computes: shard = rendezvous(origin_id, N)
    |  Stamps:   headers["x-asya-route-override"]["aggregator"] = "aggregator-{shard}"
    |
    +-->  Index 0 (parent payload)  -->  aggregator-{shard} queue
    +-->  Index 1 (slice)          -->  sub-agent -->  aggregator-{shard} queue
    +-->  Index 2 (slice)          -->  sub-agent -->  aggregator-{shard} queue
    +-->  Index 3 (slice)          -->  sub-agent -->  aggregator-{shard} queue
                                                    |
                                                    v
                                           aggregator-{shard}
                                           (Deployment replica)
                                           embedded RocksDB + PVC
                                                    |
                                           Completeness detected
                                                    |
                                                    v
                                           Emit merged envelope
```

Each aggregator shard was a separate Deployment with its own queue, PVC, and
RocksDB instance. The fan-out router computed `shard = rendezvous(origin_id, N)`
to route all messages for the same fan-out operation to the same shard.

### Embedded RocksDB Per Replica

**Rationale that was proposed**:

- Write-heavy workload: Aggregation state receives many slice arrivals (writes),
  checks completeness once (read), and deletes after emission. RocksDB's LSM-tree
  is optimized for this pattern.
- Durability without coordination: Each replica has its own PVC. State survives
  pod restarts.
- No infrastructure dependency: RocksDB is an embedded library, not a service to
  deploy.
- Horizontal scaling: Add replicas (each with its own RocksDB + PVC).

**Handler code (as proposed)**:

```python
import json
import os
import time

import jsonpointer
import rocksdb

_DB_PATH = os.environ["ASYA_FANIN_DB_PATH"]
_opts = rocksdb.Options(create_if_missing=True)
_db = rocksdb.DB(_DB_PATH, _opts)

_TRANSIENT_HEADERS = {
    "x-asya-fan-in", "x-asya-route-override",
    "x-asya-route-resolved", "x-asya-parent-id",
}

_ACTOR_NAME = os.environ["ASYA_ACTOR_NAME"]
_SHARD = os.environ.get("ASYA_POD_INDEX", "0")


def aggregator(envelope: dict) -> dict | None:
    fan_in = envelope["headers"]["x-asya-fan-in"]
    key = fan_in["origin_id"].encode("utf-8")
    idx = fan_in["slice_index"]

    existing = _db.get(key)
    if existing is None:
        state = {
            "slice_count": fan_in["slice_count"],
            "aggregation_key": fan_in["aggregation_key"],
            "results": [None] * fan_in["slice_count"],
            "received_count": 0,
            "created_at": time.time(),
            "message": None,
        }
    else:
        state = json.loads(existing)

    state["results"][idx] = envelope["payload"]

    if idx == 0:
        route = envelope["route"].copy()
        route["current"] += 1
        state["message"] = {
            "id": fan_in["origin_id"],
            "route": route,
            "headers": {k: v for k, v in envelope.get("headers", {}).items()
                        if k not in _TRANSIENT_HEADERS},
        }

    state["received_count"] += 1

    if state["received_count"] == state["slice_count"]:
        msg = state["message"]
        msg["payload"] = state["results"][0]
        jsonpointer.set_pointer(msg["payload"], state["aggregation_key"],
                                state["results"][1:])
        _db.delete(key)
        return msg

    _db.put(key, json.dumps(state).encode("utf-8"))
    return None
```

**State structure in RocksDB**:

```json
{
  "slice_count": 6,
  "aggregation_key": "/results",
  "results": [{"original_field": "preserved"}, "slice-1-result", null, null, null, null],
  "received_count": 2,
  "created_at": 1707000000.0,
  "message": {
    "id": "msg-original-abc",
    "route": {"actors": ["fan_out", "aggregator", "post_process"], "current": 2},
    "headers": {"x-asya-task-id": "task-xyz"}
  }
}
```

### Rendezvous Hashing

The fan-out router used rendezvous (Highest Random Weight) hashing to
deterministically map `origin_id` to a shard index:

```python
import os
import xxhash

_FANIN_SHARDS = int(os.environ["ASYA_FANIN_SHARDS"])

def _rendezvous_shard(origin_id, target):
    """Rendezvous (HRW): pick shard with highest hash score."""
    best = max(range(_FANIN_SHARDS),
               key=lambda i: xxhash.xxh64_intdigest(
                   f"{origin_id}:{i}".encode()))
    return f"{target}-{best}"
```

**Properties of rendezvous hashing**:
- Minimal redistribution on scale change (~1/N keys move when adding/removing a shard)
- Uniform distribution without tuning (no virtual nodes needed)
- O(N) per lookup where N is shard count (acceptable for N < 100)
- Deterministic: same origin_id always maps to the same shard

**xxHash** (xxHash64) was chosen as the hash function:
- Non-cryptographic, optimized for speed (~30 GB/s)
- Excellent avalanche properties and uniform distribution
- Deterministic (no per-process salt like Python's `hash()`)
- `xxhash` package: thin C binding with no transitive dependencies

**Alternative algorithms considered**:

| Algorithm | Redistribution (N to N+1) | Complexity | Status |
|-----------|---------------------------|------------|--------|
| `hash(key) % N` | ~100% keys redistribute | Trivial | Rejected (too much redistribution) |
| Consistent hashing | ~1/N keys redistribute | Moderate (ring + vnodes) | Planned alternative |
| Rendezvous (HRW) | ~1/N keys redistribute | Simple (argmax of hashes) | Chosen |

### Deployment (N Sharded Aggregators)

Each shard was deployed as a separate AsyncActor with its own queue:

```yaml
# aggregator-0
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator-0
spec:
  image: asya-crew:latest
  handler: asya_crew.aggregator.aggregator
  handlerMode: envelope
  transport: sqs
  # PVC for RocksDB
  volumeClaimTemplates:
    - metadata:
        name: rocksdb-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi

# aggregator-1, aggregator-2, ... (repeated N times)
```

Queue naming: `asya-{namespace}-aggregator-0`, `asya-{namespace}-aggregator-1`, etc.

### Scale-Up and Scale-Down

**Scale up (N to M, M > N)**:
1. Deploy M aggregator replicas (new shards get new queues and PVCs)
2. Redeploy fan-out router with `ASYA_FANIN_SHARDS=M`
3. In-flight fan-outs continue correctly: their messages already carry
   `x-asya-route-override` targeting shards 0..(N-1)
4. New fan-outs distribute across shards 0..(M-1)

**Scale down (N to M, M < N)** -- requires draining:
1. Redeploy fan-out router with `ASYA_FANIN_SHARDS=M`
2. Wait for shards M..(N-1) to complete all in-flight aggregations
3. Verify queues for shards M..(N-1) are empty
4. Remove aggregator Deployments M..(N-1) and their queues/PVCs

### Observability (RocksDB-Specific)

A background thread sampled RocksDB stats every 10s:

| Metric | Type | Description |
|---|---|---|
| `asya.fanin.rocksdb.size_bytes` | Gauge | Total on-disk DB size |
| `asya.fanin.rocksdb.keys` | Gauge | Approximate live key count |
| `asya.fanin.rocksdb.pending_compaction_bytes` | Gauge | Bytes pending compaction |
| `asya.fanin.rocksdb.block_cache_usage_bytes` | Gauge | Block cache memory usage |

```python
import threading

def _rocksdb_stats_loop(db, labels, interval=10):
    while True:
        rocksdb_size.set(int(db.get_property(b"rocksdb.estimate-live-data-size")), labels)
        rocksdb_keys.set(int(db.get_property(b"rocksdb.estimate-num-keys")), labels)
        rocksdb_pending.set(int(db.get_property(b"rocksdb.compaction-pending")), labels)
        rocksdb_cache.set(int(db.get_property(b"rocksdb.block-cache-usage")), labels)
        threading.Event().wait(interval)

threading.Thread(target=_rocksdb_stats_loop,
                 args=(_db, {"aggregator": _ACTOR_NAME, "shard": _SHARD}),
                 daemon=True).start()
```

Primary backpressure risk: PVC exhaustion causing RocksDB write stalls.

## Why Rejected

### 1. Contradicts Stateless Deployment principle (epic 1dmf ADR-6)

The semi-stateful actors RFC establishes that all actors remain stateless
Deployments with external state. Embedded RocksDB requires PVCs and breaks
standard KEDA autoscaling (PVC lifecycle is coupled to pod lifecycle).

### 2. Sharding adds significant complexity

- N separate AsyncActor deployments to manage
- Shard count configuration and propagation
- Scale-down requires draining (waiting for in-flight aggregations)
- Per-shard queues and PVCs
- Rendezvous hashing in generated code
- xxhash dependency

### 3. Pod failure locks state

When a pod with an embedded RocksDB crashes, its PVC data is locked until
the pod restarts. Other pods cannot access the sharded state. This creates
a recovery bottleneck.

### 4. Not truly horizontally scalable per shard

Each shard processes messages serially. Horizontal scaling only works across
shards (different origin_ids). A single fan-out with many slices is bound by
one shard's throughput.

### 5. External state + split-key is simpler and sufficient

The split-key pattern on S3 (or Redis, or any KV store) achieves:
- Zero contention (each slice writes its own key)
- No sharding needed (any pod handles any message)
- Standard KEDA autoscaling
- No PVCs or StatefulSets
- State survives pod failures without recovery delays

## When This Approach Might Be Revisited

Despite being rejected for v0, the sharded-RocksDB approach has legitimate
use cases:

- **Ultra-high throughput fan-in** with thousands of fan-out operations per
  second where network latency to external stores is the bottleneck
- **Air-gapped deployments** without access to S3, Redis, or other external
  state stores
- **Latency-critical fan-in** where sub-millisecond state access is required

If revisited, it should be implemented as a **flavor** within the extensible
architecture: `asya_crew.fanin.rocksdb_sharded.aggregator`. The fan-out router
already supports opt-in sharding via `ASYA_FANIN_SHARDS > 1`.

## References

- Semi-Stateful Actors RFC (epic 1dmf) -- ADR-6, ADR-7, ADR-8, ADR-9
- A/B Routing RFC (epic 1crb) -- `x-asya-route-override` mechanism
- [RocksDB](https://rocksdb.org/) -- Embedded key-value store
- [python-rocksdb](https://python-rocksdb.readthedocs.io/) -- Python bindings
- [xxHash](https://xxhash.com/) -- Non-cryptographic hash function
