---
title: Stateful Fan-In/Fan-Out
status: open
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
- `asya-altb` [P3] StatefulSet workload support (needed for aggregator deployment)
- `asya-zpl` [P2] Research: stateful fan-in actor (blocked by asya-0bvg)

## Critical Path
```
asya-nduw (headers) → asya-2ozv (route-override) ─┐
                                                    ├─→ asya-brq4 (integration)
asya-0bvg (sink) → asya-fi6u (aggregator) ────────┘

asya-pmor (parser) → asya-q2kp (codegen) ──────┐
asya-altb (StatefulSet) ────────────────────────┼──→ asya-1mqw (E2E)
asya-nduw + asya-2ozv + asya-fi6u + asya-0bvg ─┘
```

## RFC: Fan-In Aggregation Protocol

## Abstract

This RFC defines the aggregation (fan-in) side of Asya's fan-out/fan-in architecture. It specifies how N parallel sub-agent results are collected, merged, and emitted as a single envelope for pipeline continuation. The design uses **sharded aggregator replicas**, each with an **embedded RocksDB store**, where the fan-out router resolves shard affinity at emission time via rendezvous hashing and the `x-asya-route-override` header mechanism.

## Motivation

The [fan-out RFC](asya-fan-in-fan-out.md) defines how a fan-out router emits N+1 messages (1 parent payload + N sub-agent slices). This RFC answers the question: how does the system collect those N+1 messages back into a single envelope?

The aggregator must:

1. **Accept the parent payload** (index 0) that carries the original payload and continuation route
2. **Accept sub-agent slices** (indices 1..N) that carry individual sub-agent results
3. **Detect completeness** when all N+1 messages have arrived
4. **Emit a merged envelope** with all results assembled and route pointing to the next actor

### Requirements

- **Horizontal scalability**: A single aggregator replica must not be a bottleneck
- **Durability**: In-flight aggregation state must survive pod restarts
- **Simplicity**: No distributed database, no external coordination service
- **Affinity**: All messages for the same fan-out operation must reach the same replica

---

## Architecture Overview

```
Fan-out router (generated code)
    │
    │  Reads:    origin_id = message.id
    │  Computes: shard = rendezvous(origin_id, N)
    │  Stamps:   headers["x-asya-route-override"]["aggregator"] = "aggregator-{shard}"
    │  Stamps:   headers["x-asya-fan-in"]["origin_id"] = origin_id
    │
    ├──► Index 0 (parent payload)  ──► aggregator-{shard} queue
    ├──► Index 1 (slice)          ──► sub-agent queue ──► aggregator-{shard} queue
    ├──► Index 2 (slice)          ──► sub-agent queue ──► aggregator-{shard} queue
    └──► Index 3 (slice)          ──► sub-agent queue ──► aggregator-{shard} queue
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
- **Sidecar stays simple**: The sidecar performs a dictionary lookup on the override header (as defined in the A/B Routing RFC (epic 1crb)). No sharding logic in the sidecar.
- **Fan-out router resolves shards**: The compiler-generated fan-out router computes the shard via inline rendezvous hashing and stamps the override header on every emitted message (parent payload + all slices).
- **Number of shards known to fan-out router at deployment time**: `N` is passed to fan-out router as `ASYA_FANIN_SHARDS` env variable at deployment time.

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

**Decision**: Embedded RocksDB (via `python-rocksdb` bindings) per aggregator replica.

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

### ADR-2: Generated Fan-Out Router with Inline Sharding

**Context**: The compiled route says `"aggregator"` but messages must reach a specific shard (`"aggregator-2"`). Something must resolve the abstract name to the concrete shard. Additionally, the fan-out router must split the input into N slices — determining which actor receives which payload. Options:

| Option | Pros | Cons |
|--------|------|------|
| Standalone shard-resolver actor (separate from fan-out) | Separation of concerns | Extra queue hop per slice (N additional hops per fan-out) |
| Sidecar resolves shards | No extra hop, efficient | Adds specialized logic to the sidecar, violates simplicity principle |
| Pre-built crew actor configured via env vars | Reusable, no extra hop | Slicing logic can't be expressed in env vars for all patterns (see below) |
| **Compiler-generated router with inline sharding** | **No extra hop, handles all patterns, no crew dependency** | **Sharding utility generated per-flow (trivial — ~10 lines)** |

**Decision**: The fan-out router is a **compiler-generated router** (like existing conditional/mutation routers). The Flow DSL compiler generates both the slicing logic and the sharding utility inline in the router file. No `asya-crew` dependency.

**Why not a pre-built crew actor**: The crew actor approach requires encoding slicing logic in environment variables. This works for simple homogeneous fan-out (`ASYA_FANIN_ITERATOR=topics`) but breaks down for the full range of DSL patterns:

```python
# These patterns can't be expressed as env var configuration:
[research_agent(t) for t in p["topics"]]              # direct iteration
[research_agent(p["query"]) for _ in range(10)]        # fixed count
[sentiment_analyzer(p["text"]), topic_extractor(p["text"])]  # heterogeneous
```

Encoding these as `ASYA_FANIN_MAPPINGS` JSON blobs or `ASYA_FANIN_ITERATOR` field names trades code clarity for configuration complexity. Since the slicing logic IS code (it comes from the DSL), it should remain code in the generated router.

**How it works**: The compiler takes the DSL loop/list as-is, runs it to accumulate `(actor_name, payload)` pairs, then yields all envelopes. The sharding utility (`_rendezvous_shard`) is generated as a module-level function in the routers file (~10 lines), reading `ASYA_FANIN_SHARDS` from an env var at import time.

**Generated router structure** (for `p["results"] = [research_agent(t) for t in p["topics"]]`):

```python
def fanout_research_flow_L5(message):
    p = message["payload"]
    r = message["route"]
    c = r["current"]
    origin_id = message["id"]
    _agg = r["actors"][c + 1]
    _shard = _rendezvous_shard(origin_id, _agg)
    _hdrs = message.get("headers", {})

    # --- Accumulate: DSL loop as-is, actor call -> (name, payload) ---
    _slices = []
    for t in p["topics"]:
        _slices.append((resolve("research_agent"), t))
    # ---

    _n = len(_slices) + 1  # +1 for parent payload at index 0
    _fan_in = {"actor": _agg, "origin_id": origin_id,
               "slice_count": _n, "aggregation_key": "/results"}

    # Index 0: parent payload (first yield -> keeps original message.id)
    yield {
        "route": {"actors": list(r["actors"]), "current": c + 1},
        "headers": {**_hdrs, "x-asya-route-override": {_agg: _shard},
                    "x-asya-fan-in": {**_fan_in, "slice_index": 0}},
        "payload": json.loads(json.dumps(p)),
    }

    # Indices 1..N: sub-agent slices
    for _i, (_actor, _payload) in enumerate(_slices):
        yield {
            "route": {"actors": [_actor, _shard], "current": 0},
            "headers": {**_hdrs, "x-asya-route-override": {_agg: _shard},
                        "x-asya-fan-in": {**_fan_in, "slice_index": _i + 1}},
            "payload": _payload,
        }
```

The only part that varies per fan-out is how `_slices` is built. Everything below it is identical boilerplate emitted by the code generator. The `x-asya-fan-in` header is the same schema for all messages — only `slice_index` differs.

**Available algorithms** (configured via `ASYA_FANIN_ALGORITHM`):

| Algorithm | Status | Description |
|-----------|--------|-------------|
| `rendezvous` | Available | Rendezvous (HRW): `argmax_i(hash(origin_id, shard_i))`. Minimal redistribution on scale change (~1/N keys move). |
| `consistent` | Planned | Consistent hashing with virtual nodes. Same redistribution properties, different implementation trade-offs. |

Rendezvous is the default and only option for now.

**Rationale**:

- **No extra hop**: The fan-out router IS the sharding actor. It emits N+1 messages with shard-resolved `x-asya-route-override` headers. No separate shard-resolver needed.
- **Handles all patterns**: The DSL loop/list is copied verbatim into the generated code. Comprehensions, direct iteration, fixed count, heterogeneous lists — all produce the same `_slices` list of `(actor, payload)` tuples.
- **No crew dependency**: The sharding utility is ~10 lines of generated code. No import from `asya-crew`, no runtime library dependency.
- **Algorithm is still a deployment choice**: The generated `_rendezvous_shard` reads `ASYA_FANIN_SHARDS` from an env var. Shard count changes require redeployment of the router actor (env var change), not recompilation. Algorithm changes require regenerating the router (the ~10-line utility), but this is a rare operation.
- **Leverages existing infrastructure**: The `x-asya-route-override` header from the A/B Routing RFC (epic 1crb) provides the resolution mechanism. No new sidecar features needed.
- **Scale-up safe**: When scaling from N to M shards (M > N), old messages continue to route correctly because the target shard name is baked into the `x-asya-route-override` header at emission time. Old shards still exist. New fan-outs use new shard count.

**Consequences**:

- Adding new sharding algorithms requires updating the code generator (not `asya-crew`). Since the utility is ~10 lines, this is trivial.
- **Scale-down requires draining**: When reducing shard count, old shards must finish processing in-flight aggregations before removal. See [Open Questions](#open-questions).

### ADR-3: Rendezvous Hashing as Default Algorithm

**Context**: The generated fan-out router needs a deterministic function mapping `origin_id` to a shard index. Three algorithms were considered:

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
- **O(N) is fine**: N is the shard count (typically 3-20), not the message count. Evaluating `hash(origin_id, shard_i)` for 20 shards is sub-microsecond.

**Why not modulo**: Modulo is simpler but redistributes all keys on scale change. Rendezvous provides better scaling properties at negligible implementation cost (~10 lines of generated code).

**Why not consistent hashing (yet)**: Rendezvous achieves the same redistribution properties with less code and no tuning (vnodes). Consistent hashing will be added as a second option if use cases emerge that benefit from O(log N) lookup (very high shard counts).

**Consequences**:

- In-flight fan-outs are unaffected by shard count changes (destinations already resolved in `x-asya-route-override`). New fan-outs use the new N.
- Scale-up is safe. Scale-down requires draining old shards (TODO: another RFC once this is implemented).

### ADR-4: Hashing Algorithm Selection

**Context**: The sharding algorithms require a hash function that produces uniform distribution over `origin_id` strings (UUIDs).

**Decision**: Use `xxhash` (xxHash64) via the `xxhash` Python package.

**Rationale**:

- **Speed**: xxHash64 is one of the fastest non-cryptographic hash functions (~30 GB/s on modern CPUs). For a single `origin_id` string, hashing is effectively free.
- **Uniform distribution**: xxHash64 has excellent avalanche properties and produces uniform distribution across the output space.
- **Deterministic**: Same input always produces the same output. No salt or seed needed for this use case.
- **No cryptographic overhead**: Cryptographic hashes (SHA-256, MD5) are unnecessarily slow. The aggregator does not need collision resistance -- it needs uniform distribution for load balancing.
- **Lightweight dependency**: The `xxhash` package is a thin C binding with no transitive dependencies.

**Alternatives**:

- `hashlib.md5`: Works but 5-10x slower than xxHash. No benefit from cryptographic properties.
- `hash()` builtin: Randomized per process (PYTHONHASHSEED). Not deterministic across replicas or restarts.
- `hashlib.sha256`: Slowest option, no benefit.
- FNV-1a: Good alternative but xxHash has better distribution and speed.

**Usage in generated router code** (emitted at the top of `routers.py` by the code generator):

```python
import os

import xxhash

_FANIN_SHARDS = int(os.environ["ASYA_FANIN_SHARDS"])


def _rendezvous_shard(origin_id, target):
    """Rendezvous (HRW): pick shard with highest hash score."""
    best = max(range(_FANIN_SHARDS),
               key=lambda i: xxhash.xxh64_intdigest(f"{origin_id}:{i}".encode()))
    return f"{target}-{best}"
```

### ADR-5: `origin_id` as Aggregation Key

**Context**: The aggregator needs a stable key to group all messages belonging to the same fan-out operation, and it needs to know what `id` to assign to the merged envelope. Using `parent_id` (set by the sidecar's generator fanout mechanism) was rejected because it is fragile through envelope-mode sub-agent hops and couples fan-in to sidecar internals.

**Decision**: The fan-out router reads the incoming `message.id`, stores it as `origin_id` in the `x-asya-fan-in` header on all emitted messages (parent payload + slices), and uses it for three purposes:

1. **Aggregation key** in RocksDB
2. **Rendezvous hash input** for shard selection
3. **Merged envelope ID** — restored on the merged envelope so downstream actors see the same message identity

**Rationale**:

- **`message.id` is internal**: The `message.id` field is a unique identifier of the message object itself. It is managed by the sidecar (kept on first yield, new UUID on subsequent yields) and is not used in any aggregation, routing, or tracking logic. Gateway tracking uses separate headers (`x-asya-task-id`, `x-asya-request-id`). The `message.id` field exists solely for message-level deduplication and debugging.
- **Decoupled from sidecar ID assignment**: The aggregator reads `origin_id` from `x-asya-fan-in`, not from `message.id` or `x-asya-parent-id`. Sidecar ID assignment rules have zero impact on fan-in.
- **Survives arbitrary sub-agent hops**: The `x-asya-fan-in` header is part of `headers`, which is preserved by the runtime in both payload and envelope modes. Even envelope-mode intermediate actors must propagate headers for routing (e.g., `x-asya-route-override`), so `x-asya-fan-in` is preserved too.
- **Unique per fan-out**: Each incoming message has a unique `message.id` (UUID). Sequential fan-outs don't collide because the aggregator deletes the key after emitting the merged envelope, and the next fan-out cannot start until it receives that merged output.
- **Retry-idempotent**: If the fan-out router crashes and the message is redelivered (same `message.id`), the same `origin_id` routes to the same shard and same aggregation key — no orphaned state.

**Consequences**:

- Single UUID field in the header (~36 bytes).
- The aggregator code is simple: `key = fan_in["origin_id"]`, merged envelope gets `id = state["origin_id"]`.
- The broader protocol changes (moving `parent_id` to `x-asya-parent-id` header, gateway tracking headers) are out of scope for this RFC and can proceed independently.

---

## Fan-In Protocol

### Message ID Semantics

Fan-in is **fully abstract from message identity**. The aggregator never inspects `message.id` — it is an internal unique identifier of the message object, managed by the sidecar, and not used in any aggregation or routing logic.

The fan-in protocol carries all needed identifiers in its own `x-asya-fan-in` header:

- **`origin_id`**: The original `message.id` before fan-out. Serves three roles: aggregation key, rendezvous hash input, and the `id` restored on the merged envelope. Set by the fan-out router (it reads `message.id` before yielding). See ADR-5.

Other identity headers that may be present on messages are **orthogonal** to fan-in:

- **`x-asya-parent-id`** (set by sidecar): Links a yielded message to its originator. Tracing/debugging only — not used in logic. Set on 2nd+ yields (see "Yield Order" below).
- **`x-asya-task-id`** or **`x-asya-request-id`** (set by gateway): Tracks the A2A task or MCP tool call that initiated the pipeline. Used for status reporting to gateway. Fan-in preserves these headers on the merged envelope but does not read them.

### Yield Order and ID Assignment

The generated fan-out router yields messages via the sidecar's generator mechanism. The sidecar assigns IDs based on yield position:

1. **First yield** (`partial=False`): `message.id` is kept unchanged. No `parent_id` / `x-asya-parent-id`.
2. **Each subsequent yield** (`partial=False`): `message.id = uuid4()`. Sidecar sets `parent_id = original_message.id`.
3. **Streaming events** (`partial=True`): Each event gets a new `message.id = uuid4()`. Sidecar sets `parent_id = original_message.id`.

The fan-out router **yields the parent payload first (slice index 0), then sub-agent slices (indices 1..N)**. This is an optimization: the first yield keeps the original `message.id`, while each subsequent yield gets a fresh UUID.

**Why `uuid4()` instead of `{id}-{index}`**: The current sidecar uses `fmt.Sprintf("%s-%d", msg.ID, index)`. This has a **collision bug** in pipelines with multiple fan-out actors. Since index 0 keeps the original `message.id`, a message passing through two separate fan-out actors produces duplicate child IDs:

```
Actor A fans out 3:  msg, msg-1, msg-2
                      |
                      v (index 0 keeps "msg")
Actor C fans out 2:  msg, msg-1   <-- COLLISION: msg-1 already exists from Actor A
```

With `uuid4()`, each fan-out generates globally unique IDs. No collision possible regardless of pipeline topology. Additionally, `parent_id` and `root_id` headers carry the lineage, so `message.id` doesn't need to encode ancestry. This is a planned change to the sidecar (`handleSuccessResponse()` at router.go:580).

**Fire-and-forget semantics**: Yield-only fan-out (without fan-in) is fire-and-forget. Only the first message (index 0) is tracked by the gateway — it keeps the original `message.id`, so SSE streaming and task tracking continue to work. Subsequent yields (index > 0, `parent_id` set) are side effects that proceed independently. When they reach x-sink, they are acked silently without gateway reporting (see [Non-Reporting Mechanisms](#non-reporting-mechanisms-in-x-sink-and-x-sump)).

**Nested fan-out tracing**: When a fan-out child itself fans out, `parent_id` only links to the immediate parent. To trace back to the ultimate root across arbitrary depth, use `root_id = root_id or parent_id` — if a `root_id` already exists (from a prior fan-out), preserve it; otherwise derive it from `parent_id`. This should live in a header (`x-asya-root-id`). See rfc-actor-states.md (rfc0 branch) for full analysis.

### Addressed Fan-In

The `x-asya-fan-in` header is **transient**: it exists only on messages between the fan-out router and the aggregator. The fan-out router stamps it at emission time; the aggregator reads it and strips it from the merged envelope before emitting to the continuation actor. Outside of the fan-out/fan-in segment of the pipeline, this header is not present.

The header includes an `actor` field that identifies the target aggregator actor. The aggregator checks `x-asya-fan-in.actor == ASYA_ACTOR_NAME` to confirm the header is addressed to it.

The `origin_id` (original `message.id`) serves as the aggregation key. It is stamped into every `x-asya-fan-in` header and is used as the RocksDB storage key. This decouples aggregation from sidecar ID assignment entirely (see ADR-5).

For sequential fan-outs in the same flow, each fan-out has a different `origin_id` because the aggregator deletes the key after emitting, and the next fan-out receives a merged envelope (with the restored `origin_id` as its `message.id`):

```python
def multi_fanout(p: dict) -> dict:
    # Fan-out 1: origin_id = message.id of incoming envelope
    p["research"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
    # Fan-out 2: origin_id = message.id of merged envelope from fan-out 1
    #            (same value, but key was deleted after fan-out 1 completed)
    p["reviews"] = [review_agent(p["research"][i]) for i in range(len(p["research"]))]
    return p
```

### Unified Message Schema

All fan-in messages (parent payload and sub-agent slices) share the same `x-asya-fan-in` header schema. There is no `type` discriminator — the aggregator distinguishes the parent payload by `slice_index == 0`.

The fan-out router yields N+1 messages total:
- **Index 0** (parent payload): Carries the original payload and continuation route. Yielded first, so it keeps the original `message.id`.
- **Indices 1..N** (sub-agent slices): Each carries a sub-agent's input payload and a route through the sub-agent to the aggregator. Yielded 2nd+, so each gets a new UUID from the sidecar.

**Index 0 message** (parent payload, yielded first):

```json
{
  "id": "msg-original-abc",
  "route": {
    "actors": ["start", "fan_out", "aggregator", "post_process"],
    "current": 2
  },
  "headers": {
    "x-asya-route-override": {"aggregator": "aggregator-2"},
    "x-asya-fan-in": {
      "actor": "aggregator",
      "origin_id": "msg-original-abc",
      "slice_index": 0,
      "slice_count": 6,
      "aggregation_key": "/results"
    }
  },
  "payload": {
    "original_field": "preserved"
  }
}
```

**Index 1..N message** (sub-agent slice, yielded after index 0):

```json
{
  "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "route": {
    "actors": ["sub_agent", "aggregator"],
    "current": 0
  },
  "headers": {
    "x-asya-parent-id": "msg-original-abc",
    "x-asya-route-override": {"aggregator": "aggregator-2"},
    "x-asya-fan-in": {
      "actor": "aggregator",
      "origin_id": "msg-original-abc",
      "slice_index": 1,
      "slice_count": 6,
      "aggregation_key": "/results"
    }
  },
  "payload": {
    "input_for_sub_agent": "topic 0"
  }
}
```

Note: `slice_count` is N+1 (5 sub-agent slices + 1 parent payload = 6). After the sub-agent processes the slice, the sub-agent's result replaces the payload before reaching the aggregator.

### Fan-In Metadata Header

Fan-in coordination uses `x-asya-fan-in` header (separate from `x-asya-route-override`). All messages share the same schema:

| Field | Description |
|-------|-------------|
| `actor` | Target aggregator actor. Aggregator checks this matches its `ASYA_ACTOR_NAME`. |
| `origin_id` | Original `message.id` before fan-out. Used as aggregation key, rendezvous hash input, and `id` of the merged envelope (see ADR-5). |
| `slice_index` | Position in the results array. `0` = parent payload (original payload + continuation route), `1..N` = sub-agent results. |
| `slice_count` | Total messages expected: N sub-agent slices + 1 parent payload. |
| `aggregation_key` | RFC 6901 JSON Pointer into the parent payload where the sub-agent results list is placed (e.g., `/results`). Present on all messages for schema uniformity. |

---

## Aggregator Actor Design

### Handler Implementation

The aggregator is a crew actor running in envelope mode. It persists state to a local RocksDB instance.

State structure stores all payloads in a single `results` array. Index 0 holds the parent payload (from the fan-out router), indices 1..N hold sub-agent results. The `message` field stores the envelope metadata (route, headers) needed to reconstruct the merged envelope:

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
_LABELS = {"aggregator": _ACTOR_NAME, "shard": _SHARD}


def aggregator(envelope: dict) -> dict | None:
    fan_in = envelope["headers"]["x-asya-fan-in"]
    key = fan_in["origin_id"].encode("utf-8")
    idx = fan_in["slice_index"]

    existing = _load(key)
    if existing is None:
        state = {
            "slice_count": fan_in["slice_count"],
            "aggregation_key": fan_in["aggregation_key"],
            "results": [None] * fan_in["slice_count"],
            "received_count": 0,
            "created_at": time.time(),
            "message": None,
        }
        fanin_active.add(1, _LABELS)
    else:
        state = existing

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
    fanin_messages.add(1, _LABELS)

    if state["received_count"] == state["slice_count"]:
        msg = state["message"]
        msg["payload"] = state["results"][0]
        jsonpointer.set_pointer(msg["payload"], state["aggregation_key"],
                                state["results"][1:])
        _db.delete(key)
        fanin_completions.add(1, _LABELS)
        fanin_active.add(-1, _LABELS)
        fanin_duration.record(time.time() - state["created_at"], _LABELS)
        return msg

    _save(key, state)
    return None


def _load(key: bytes) -> dict | None:
    data = _db.get(key)
    return json.loads(data) if data else None


def _save(key: bytes, state: dict):
    _db.put(key, json.dumps(state).encode("utf-8"))
```

### Behavior

- **Completeness**: Every message increments `received_count`. The last arrival (whichever it is) finds `received_count == slice_count` and emits. All others return `None` (ack, routed to x-sink).
- **Index 0 before slices**: If sub-agent slices arrive before the parent payload (index 0), they fill `results[idx]` into partial state. When index 0 arrives, it fills `state["message"]` (route + headers). Completeness check still works — emission requires all indices filled.
- **Ordering**: Results are placed at `results[slice_index]`, preserving DSL order regardless of arrival order. On emission, `results[0]` becomes the base payload and `results[1:]` is placed at `aggregation_key`.
- **Multiple fan-ins**: Each fan-out uses a different `origin_id` (unique `message.id`). Sequential fan-outs don't collide because the key is deleted after emitting.

### Non-Reporting Mechanisms in x-sink and x-sump

When the aggregator returns `None` (still accumulating), the sidecar acks the message and routes it to x-sink with `status.phase = "succeeded"` (the sidecar always overwrites the phase). Without special handling, x-sink would report a false "finished" status to the gateway.

x-sink and x-sump use **three independent mechanisms** to suppress gateway reporting, evaluated in this order:

#### 1. `x-asya-fan-in` header detection

- **When**: Message has `x-asya-fan-in` header → it's a partial fan-in result
- **x-sink**: Ack and consume. Persist to S3 if configured, run hooks if configured. Do NOT report to gateway.
- **x-sump**: Log the error, persist to S3 if configured. Do NOT report to gateway. The aggregator will detect the incomplete fan-out via TTL cleanup (see [Open Questions](#open-questions)).
- **Why checked first**: Fan-in index 0 (parent payload) has NO `parent_id` but must still be suppressed. The `x-asya-fan-in` header is the only reliable signal.

The `x-asya-fan-in` header is already on the message because it was stamped by the fan-out router and preserved through the aggregator. This requires no sidecar changes.

#### 2. `parent_id` detection (fire-and-forget yield children)

- **When**: Message has `parent_id` set and NO `x-asya-fan-in` header → it's a fire-and-forget yield child
- **x-sink**: Ack and consume. Persist to S3 if configured. Run hooks only if `ASYA_SINK_FANOUT_HOOKS=true` (default: `false`). Do NOT report to gateway.
- **x-sump**: Log the error, persist to S3 if configured. Do NOT report to gateway.
- **Rationale**: Yield-only fan-out is fire-and-forget. Only the first yield (index 0, keeps original `message.id`) is tracked by the gateway. Subsequent yields are side effects.
- **`ASYA_SINK_FANOUT_HOOKS`** (optional, default `false`): Controls whether registered finalizer hooks run for fan-out children. Disabled by default because fan-out can produce many messages and hooks (e.g., Slack notifications, webhook calls) would fire per child. Enable for audit/observability use cases.

#### 3. Non-terminal `status.phase` (asya-0bvg)

- **When**: `status.phase` is not in `{"succeeded", "failed"}` (e.g., `"awaiting_approval"`)
- **x-sink**: Ack and consume. Persist to S3 if configured, run hooks if configured. Do NOT report to gateway.
- **x-sump**: Log at INFO level. Persist to S3 if configured. Do NOT report to gateway.
- **Scope**: Human-in-the-loop, future custom states.
- **Prerequisite**: Sidecar must be updated to preserve custom phases from runtime responses (currently always overwrites to `"succeeded"` or `"failed"`).

#### Summary

All three mechanisms persist to S3. Gateway reporting is always suppressed. Hooks are configurable for fan-out children via `ASYA_SINK_FANOUT_HOOKS`.

| # | Signal | Run hooks? | Report gateway? |
|---|--------|-------------|-----------------|
| 1 | `x-asya-fan-in` header present | configurable | ❌ |
| 2 | `parent_id` set (no fan-in header) | configurable | ❌ |
| 3 | Non-terminal `status.phase` | ✅ | ❌ |
| — | None of the above | ✅ | ✅ |

`ASYA_SINK_FANOUT_HOOKS` (default: `false`) — when `false`, hooks are skipped for messages with `parent_id` set (fire-and-forget children). Set to `true` to run hooks on every fan-out child.

Mechanisms 1 and 2 work today (signals are already set by the fan-out router and sidecar). Mechanism 3 requires sidecar changes (asya-0bvg). See rfc-actor-states.md (rfc0 branch) for the full phase lifecycle analysis.

---

## Deployment

### StatefulSet Configuration

Each aggregator shard is a StatefulSet replica with a PVC for RocksDB storage (TODO: need to support `StatefulSet` workload type):

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
    - name: ASYA_FANIN_DB_PATH
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

### Fan-Out Router Deployment

The fan-out router is a compiler-generated actor. It uses the generated `routers.py` module (same as conditional/mutation routers) and requires only `ASYA_FANIN_SHARDS` as deployment-time configuration:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: fanout-research-flow-l5
spec:
  image: my-flow-routers:latest
  handler: routers.fanout_research_flow_L5
  handlerMode: envelope
  env:
    - name: ASYA_FANIN_SHARDS
      value: "3"                        # number of aggregator shards
    - name: ASYA_HANDLER_RESEARCH_AGENT
      value: "research-agent"           # actor name resolution (same as other routers)
```

---

## Scaling Behavior

### Scale Up (N to M, M > N)

1. Deploy M aggregator replicas (new shards get new queues and PVCs)
2. Redeploy fan-out router with `ASYA_FANIN_SHARDS=M`
3. In-flight fan-outs continue correctly: their messages already carry `x-asya-route-override` targeting shards 0..(N-1), which still exist
4. New fan-outs distribute across shards 0..(M-1)

**Safe**: No data loss, no coordination needed.

### Scale Down (N to M, M < N)

Scaling down requires draining shards M..(N-1) before removal:

1. Redeploy fan-out router with `ASYA_FANIN_SHARDS=M` (new fan-outs only target shards 0..(M-1))
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

The fan-in sharding mechanism reuses the `x-asya-route-override` header from the A/B Routing RFC (epic 1crb). This is explicitly listed as Use Case 4 in that RFC.

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

## Observability

Fan-out/fan-in introduces distributed state (RocksDB) and multi-message coordination that require dedicated metrics. All metrics are exported via OpenTelemetry (OTel) using the `opentelemetry-api` Python SDK, following the [OTel semantic conventions](https://opentelemetry.io/docs/specs/semconv/) naming style (`dotted.lowercase`).

### Fan-Out Router Metrics

Emitted by the generated fan-out router. Since the router is generated code, the code generator emits OTel instrumentation alongside the routing logic.

| Metric | Type | Description |
|---|---|---|
| `asya.fanout.operations` | Counter | Fan-out operations initiated (one per incoming message) |
| `asya.fanout.slices` | Histogram | Number of sub-agent slices per fan-out operation. Detects unexpectedly large fan-outs (e.g., iterating over a 10k-element list). |

**Labels**: `flow` (flow name), `aggregator` (target aggregator actor name).

**Backpressure signal**: A fan-out emitting thousands of slices can overwhelm sub-agent queues and the aggregator. The `asya.fanout.slices` histogram provides visibility into fan-out cardinality. Alerting on p99 > threshold catches runaway fan-outs before they saturate infrastructure.

### Aggregator Metrics

Emitted by the aggregator crew actor. A background thread periodically samples RocksDB stats and updates gauges.

**Fan-in coordination metrics**:

| Metric | Type | Description |
|---|---|---|
| `asya.fanin.active` | UpDownCounter | In-flight aggregations (incremented on first message for a new `origin_id`, decremented on completion or TTL cleanup) |
| `asya.fanin.messages.received` | Counter | Total messages received (parent payloads + sub-agent slices) |
| `asya.fanin.completions` | Counter | Completed aggregations (all slices arrived, merged envelope emitted) |
| `asya.fanin.duration_seconds` | Histogram | Wall-clock time from first message arrival to completion. Requires storing a `created_at` timestamp in aggregation state. |
| `asya.fanin.stale_cleanups` | Counter | Aggregation entries expired by TTL (partial fan-out failures) |

**Labels**: `aggregator` (actor name), `shard` (shard index, e.g., `"2"`).

**RocksDB storage metrics** (sampled every 10s by a background thread):

| Metric | Type | Description |
|---|---|---|
| `asya.fanin.rocksdb.size_bytes` | Gauge | Total on-disk DB size. Primary backpressure signal — alert when approaching PVC capacity. |
| `asya.fanin.rocksdb.keys` | Gauge | Approximate number of live keys (`rocksdb.estimate-num-keys` property). Correlates with `asya.fanin.active`. |
| `asya.fanin.rocksdb.pending_compaction_bytes` | Gauge | Bytes pending compaction. Sustained high values indicate write pressure exceeding compaction throughput. |
| `asya.fanin.rocksdb.block_cache_usage_bytes` | Gauge | Block cache memory usage. Useful for tuning `block_cache_size`. |

**Labels**: `aggregator` (actor name), `shard` (shard index).

### Backpressure and Alerting

The primary risk is PVC exhaustion on aggregator shards. RocksDB will crash (write stall, then I/O error) if the volume fills up. Recommended alerts:

| Alert | Condition | Severity |
|---|---|---|
| AggregatorDiskHigh | `asya.fanin.rocksdb.size_bytes / pvc_capacity > 0.8` | Warning |
| AggregatorDiskCritical | `asya.fanin.rocksdb.size_bytes / pvc_capacity > 0.95` | Critical |
| AggregatorStaleFanouts | `asya.fanin.active` growing without `asya.fanin.completions` increasing | Warning |
| FanoutCardinalityHigh | `asya.fanout.slices` p99 > 1000 | Warning |

PVC capacity is known at deployment time (`volumeClaimTemplates.resources.requests.storage`). It can be injected as an env var (`ASYA_FANIN_PVC_CAPACITY_BYTES`) for the aggregator to compute utilization ratios locally, or the alert can be computed externally by joining the metric with PVC metadata.

### OTel Integration

The aggregator initializes the OTel metrics SDK at startup. The exporter is configured via standard OTel environment variables (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, etc.), which are set on the AsyncActor spec.

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

_reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10000)
metrics.set_meter_provider(MeterProvider(metric_readers=[_reader]))
_meter = metrics.get_meter("asya.fanin")

fanin_active = _meter.create_up_down_counter("asya.fanin.active")
fanin_completions = _meter.create_counter("asya.fanin.completions")
fanin_messages = _meter.create_counter("asya.fanin.messages.received")
fanin_duration = _meter.create_histogram("asya.fanin.duration_seconds")
fanin_stale = _meter.create_counter("asya.fanin.stale_cleanups")

rocksdb_size = _meter.create_gauge("asya.fanin.rocksdb.size_bytes")
rocksdb_keys = _meter.create_gauge("asya.fanin.rocksdb.keys")
rocksdb_pending = _meter.create_gauge("asya.fanin.rocksdb.pending_compaction_bytes")
rocksdb_cache = _meter.create_gauge("asya.fanin.rocksdb.block_cache_usage_bytes")
```

The background thread for RocksDB stats:

```python
import threading

def _rocksdb_stats_loop(db, labels, interval=10):
    while True:
        rocksdb_size.set(int(db.get_property(b"rocksdb.estimate-live-data-size")), labels)
        rocksdb_keys.set(int(db.get_property(b"rocksdb.estimate-num-keys")), labels)
        rocksdb_pending.set(int(db.get_property(b"rocksdb.compaction-pending")), labels)
        rocksdb_cache.set(int(db.get_property(b"rocksdb.block-cache-usage")), labels)
        threading.Event().wait(interval)

threading.Thread(target=_rocksdb_stats_loop, args=(_db, {"aggregator": _ACTOR_NAME, "shard": _SHARD}),
                 daemon=True).start()
```

For the generated fan-out router, the code generator emits OTel counter increments in the router function. The OTel SDK is initialized once at module level in the generated `routers.py`.

---

## Flow DSL Examples and Code Generation

The Flow DSL supports fan-out via list comprehensions (homogeneous — same actor, different data) and list literals (heterogeneous — different actors). Both compile to the same N+1 message protocol using a single code generation strategy.

### Three Syntax Levels

The DSL supports three syntax levels for fan-out. All compile to the **same** distributed fan-out/fan-in — the difference is only in local execution semantics:

| Syntax | Local Execution | Compiled (Asya) | Flow Type |
|---|---|---|---|
| `[actor(x) for x in items]` | Sequential (sync) | Parallel fan-out (compiler optimization) | `def` |
| `[await actor(x) for x in items]` | Sequential (async, one at a time) | Parallel fan-out (compiler optimization) | `async def` |
| `await asyncio.gather(*(actor(x) for x in items))` | Parallel (async, concurrent) | Parallel fan-out | `async def` |

**Compiler optimization**: List comprehensions with actor calls have no data dependencies between iterations. The compiler automatically promotes them to parallel fan-out on Asya — even though they run sequentially locally. This is analogous to how a C compiler can auto-vectorize a loop.

The user chooses syntax based on local execution needs. If local parallelism matters (e.g., testing I/O-bound actors), use `asyncio.gather`. Otherwise, the simpler list comprehension still gets distributed parallelism on Asya.

**Examples**:

```python
# Level 1: Sync comprehension (simplest)
def research_flow(p: dict) -> dict:
    p["results"] = [research_agent(t) for t in p["topics"]]
    return p

# Level 2: Async comprehension (sequential locally, parallel on Asya)
async def research_flow(p: dict) -> dict:
    p["results"] = [await research_agent(t) for t in p["topics"]]
    return p

# Level 3: asyncio.gather (parallel locally AND on Asya)
async def research_flow(p: dict) -> dict:
    p["results"] = await asyncio.gather(
        *(research_agent(t) for t in p["topics"])
    )
    return p
```

All three compile to the same generated fan-out router. The async variants require the agentic compiler (separate RFC) but produce the same `FanOutCall` IR node and the same N+1 message protocol.

### Code Generation Strategy

The compiler takes the DSL loop/list **as-is** and generates a router that:

1. Runs the loop to **accumulate** `(actor_name, payload)` tuples into a `_slices` list
2. Yields the **parent payload** at index 0 (first yield keeps original `message.id`)
3. Yields all **sub-agent slices** at indices 1..N

The only part that varies per fan-out is how `_slices` is built. The emission boilerplate is identical.

### All Supported Patterns

| DSL syntax | Generated `_slices` accumulation | `_n` (slice_count) |
|---|---|---|
| `[f(t) for t in p["topics"]]` | `for t in p["topics"]: _slices.append(...)` | `len(p["topics"]) + 1` |
| `[f(p["topics"][i]) for i in range(len(p["topics"]))]` | `for i in range(len(p["topics"])): _slices.append(...)` | `len(p["topics"]) + 1` |
| `[f(p["query"]) for _ in range(10)]` | `for _ in range(10): _slices.append(...)` | `11` |
| `[a(p["text"]), b(p["text"]), c(p["text"])]` | `_slices = [(resolve("a"), p["text"]), ...]` | `4` |
| `await asyncio.gather(*(f(t) for t in items))` | Same as comprehension | `len(items) + 1` |
| `await asyncio.gather(a(x), b(y), c(z))` | Same as list literal | `4` |

### Homogeneous Fan-Out (List Comprehension)

**DSL**:

```python
def research_flow(p: dict) -> dict:
    p["results"] = [research_agent(t) for t in p["topics"]]
    p = post_processor(p)
    return p
```

**Generated router**:

```python
def fanout_research_flow_L2(message):
    p = message["payload"]
    r = message["route"]
    c = r["current"]
    origin_id = message["id"]
    _agg = r["actors"][c + 1]
    _shard = _rendezvous_shard(origin_id, _agg)
    _hdrs = message.get("headers", {})

    # --- Accumulate: DSL loop as-is, actor call -> (name, payload) ---
    _slices = []
    for t in p["topics"]:
        _slices.append((resolve("research_agent"), t))
    # ---

    _n = len(_slices) + 1
    _fan_in = {"actor": _agg, "origin_id": origin_id,
               "slice_count": _n, "aggregation_key": "/results"}

    # Index 0: parent payload (first yield -> keeps original message.id)
    yield {
        "route": {"actors": list(r["actors"]), "current": c + 1},
        "headers": {**_hdrs, "x-asya-route-override": {_agg: _shard},
                    "x-asya-fan-in": {**_fan_in, "slice_index": 0}},
        "payload": json.loads(json.dumps(p)),
    }

    # Indices 1..N: sub-agent slices
    for _i, (_actor, _payload) in enumerate(_slices):
        yield {
            "route": {"actors": [_actor, _shard], "current": 0},
            "headers": {**_hdrs, "x-asya-route-override": {_agg: _shard},
                        "x-asya-fan-in": {**_fan_in, "slice_index": _i + 1}},
            "payload": _payload,
        }
```

**Compiled to**: One fan-out router, one sub-agent actor (`research_agent`), one aggregator. All slices share the same route through `research_agent`.

### Heterogeneous Fan-Out (List Literal)

**DSL**:

```python
def analysis_flow(p: dict) -> dict:
    p["result"] = [
        sentiment_analyzer(p["text"]),
        topic_extractor(p["text"]),
        entity_recognizer(p["text"]),
    ]
    p = merge_analysis(p)
    return p
```

**Generated `_slices` block** (only this part differs from the homogeneous case):

```python
    # --- Accumulate: DSL list literal, each actor call -> (name, payload) ---
    _slices = [
        (resolve("sentiment_analyzer"), p["text"]),
        (resolve("topic_extractor"),    p["text"]),
        (resolve("entity_recognizer"),  p["text"]),
    ]
    # ---
```

The emission boilerplate is identical. Each slice routes to a different actor but all converge on the same aggregator.

### Other Patterns

**Index-based iteration** (`p["results"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]`):

```python
    _slices = []
    for i in range(len(p["topics"])):
        _slices.append((resolve("research_agent"), p["topics"][i]))
```

**Fixed count / redundancy** (`p["results"] = [research_agent(p["query"]) for _ in range(10)]`):

```python
    _slices = []
    for _ in range(10):
        _slices.append((resolve("research_agent"), p["query"]))
```

---

## Open Questions

### 1. Configuration Mechanism for Shard Count

How does the fan-out router learn `ASYA_FANIN_SHARDS`? Options:

- **Simple env var**: Set on the fan-out router's AsyncActor spec. Requires redeployment to change. This is the current approach — the generated `_rendezvous_shard` reads it at import time.
- **ConfigMap**: Fan-out router reads from a ConfigMap. Can be updated without redeployment (if router watches for changes).
- **Operator injection**: Operator injects shard count from the aggregator's replica count into the fan-out router's environment. Declarative, but couples operator resources.

Decision deferred until the operator deployment model for StatefulSet actors is finalized.

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

### 4. Header Syntax Constraints for Transport Compatibility

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
| `x-asya-fan-in` | Fan-out router | `{"actor":"...","type":"...","origin_id":"uuid",...}` (~150 bytes) |
| `x-asya-parent-id` | Sidecar (yield) | UUID string (~36 bytes). Tracing only. |
| `x-asya-task-id` | Gateway | UUID string (~36 bytes). A2A/MCP tracking. |
| `x-asya-experiment` | Experiment router | String (~30 bytes) |
| `x-asya-variant` | Experiment router | String (~30 bytes) |
| | | **7 of 10 SQS slots** |

This leaves 3 slots for user-defined headers (`trace_id`, `priority`, etc.).

**Design constraints for this RFC**:

- `x-asya-fan-in` is a single object (not a list) -- a message participates in at most one fan-in at a time
- All values must serialize to JSON strings under 1024 bytes (Pub/Sub limit)
- The `actor` field ensures the aggregator can identify headers addressed to it without consuming additional attribute slots

**Broader question**: A dedicated RFC should define the general header contract -- naming conventions, size budgets, transport promotion rules, and reserved vs user-defined header namespaces. This is out of scope for the fan-in RFC but noted here as a dependency.

### 5. Nested Fan-Out

Can a sub-agent itself fan-out? This creates a tree of aggregations. The current design supports this because:

- Each fan-out uses the incoming `message.id` as `origin_id`
- Nested fan-outs receive different `message.id` values (sidecar assigns new UUIDs to yielded slices)
- Each aggregation is independent

However, the continuation route for a nested fan-out must correctly point back to the outer aggregator. This requires the inner fan-out router to preserve the outer route context. Design deferred until the use case is validated.

### 6. Partial Failure Semantics

What happens when some sub-agent slices succeed and others fail (routed to x-sump)?

- **All-or-nothing**: Aggregator waits for all N slices. If any fail, TTL cleanup eventually expires the incomplete aggregation. The entire fan-out is treated as failed.
- **Best-effort**: Aggregator emits partial results after TTL, filling failed slots with `null` or an error marker. The continuation receives a partially-populated results list.
- **`return_exceptions` mode** (inspired by `asyncio.gather(return_exceptions=True)`): Failed slices are represented as error objects in the results list instead of aborting the aggregation.

Current design is effectively all-or-nothing (TTL cleanup deletes stale state). Best-effort and `return_exceptions` modes would require the aggregator to track per-slice failure status and a mechanism for x-sump to notify the aggregator that a slice has permanently failed (rather than being retried). Design deferred until failure patterns are observed in practice.

### 7. Payload Size and S3 Offloading

For fan-outs with large parent payloads, the index-0 message carries the full original payload through the aggregator queue. This is likely not a problem in practice — message size limits (SQS: 256KB, RabbitMQ: configurable) apply uniformly to all actor messages, and fan-out doesn't amplify the parent payload size (slices carry only their extracted data).

If payload size becomes a concern, a future optimization could offload large payloads to S3/artifact storage and replace them with references. This is orthogonal to fan-in and would benefit all actors, not just fan-out.

### 8. Gateway Tracking Headers

For A2A and MCP use-cases, the gateway needs to track the status of user-initiated requests across the actor mesh. Currently it tracks using `message["id"]` but it's becoming incorrect for fan-out use-cases. The gateway sets a tracking header on the initial message:

- **`x-asya-task-id`**: Set by gateway for A2A tasks. Used by sidecars when reporting progress/final status to `POST /tasks/{id}/progress` and `POST /tasks/{id}/final`.
- **`x-asya-request-id`**: Set by gateway for MCP tool calls. Same reporting purpose.

These headers are **orthogonal to fan-in**. The aggregator preserves them on the merged envelope (they are not stripped), so status reporting continues correctly after fan-out/fan-in.

The broader protocol change --- moving `parent_id` from a top-level envelope field to the `x-asya-parent-id` header (tracing only) and establishing `message.id` as an internal identifier not used in logic --- is out of scope for this RFC. It affects sidecar, runtime, and gateway and should be tracked as a separate protocol evolution bead.

---

## RFC References

- A/B Routing RFC (epic 1crb) -- `x-asya-route-override` header mechanism
- [JSON Pointer (RFC 6901)](https://www.rfc-editor.org/rfc/rfc6901) -- Standard for addressing values within JSON documents
- [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) -- Python implementation of JSON Pointer (zero dependencies)
- [RocksDB](https://rocksdb.org/) -- Embedded key-value store
- [python-rocksdb](https://python-rocksdb.readthedocs.io/) -- Python bindings for RocksDB
- [xxHash](https://xxhash.com/) -- Non-cryptographic hash function

## References
- RFC: docs/rfc/rfc-actor-states.md
- Related: docs/rfc/asya-bi8-agentic-asya.md
- Dependency: Stateful Actors epic (`1c87`)


---
_Migrated from beads `asya-7qh`_
