
## RFC: Fan-In Aggregation Protocol

## Abstract

This RFC defines the aggregation (fan-in) side of Asya's fan-out/fan-in architecture. It specifies how N parallel sub-agent results are collected, merged, and emitted as a single envelope for pipeline continuation.

The v0 design uses a **split-key storage pattern on S3** via the state proxy sidecar (epic 1dmf). Each slice writes to its own key (zero contention), completeness is detected by listing, and exactly-once emission uses atomic create-if-not-exists. No sharding, no CAS, no embedded databases.

The design is **extensible**: the fan-in protocol is backend-agnostic. Future aggregator flavors (Redis with CAS, sharded with rendezvous, embedded RocksDB) plug in as alternative handler modules without changing the protocol or the fan-out router.

## Motivation

The [fan-out RFC](asya-fan-in-fan-out.md) defines how a fan-out router emits N+1 messages (1 parent payload + N sub-agent slices). This RFC answers the question: how does the system collect those N+1 messages back into a single envelope?

The aggregator must:

1. **Accept the parent payload** (index 0) that carries the original payload and continuation route
2. **Accept sub-agent slices** (indices 1..N) that carry individual sub-agent results
3. **Detect completeness** when all N+1 messages have arrived
4. **Emit a merged envelope** with all results assembled and route pointing to the next actor

### Requirements

- **Horizontal scalability**: Aggregator scales via standard KEDA autoscaling
- **Durability**: In-flight aggregation state must survive pod restarts (external storage)
- **Simplicity**: No distributed database, no coordination service, no shard affinity
- **Zero contention**: Concurrent slice arrivals must not conflict with each other
- **Extensibility**: Backend-agnostic protocol; aggregator handler is pluggable

---

## Architecture Overview

```
Fan-out router (generated code)
    |
    |  Reads:    origin_id = message.id
    |  Stamps:   headers["x-asya-fan-in"] = {origin_id, slice_index, slice_count, ...}
    |
    +-->  Index 0 (parent payload)  -->  aggregator queue
    +-->  Index 1 (slice)          -->  sub-agent queue -->  aggregator queue
    +-->  Index 2 (slice)          -->  sub-agent queue -->  aggregator queue
    +-->  Index 3 (slice)          -->  sub-agent queue -->  aggregator queue
                                                         |
                                                         v
                                                aggregator
                                                (single Deployment)
                                                state proxy --> S3
                                                /state/fanin/{origin_id}/
                                                         |
                                                Completeness via listing
                                                         |
                                                         v
                                                Emit merged envelope
                                                to continuation actor
```

### Key Properties

- **No sharding**: Single aggregator Deployment with one queue. Any pod handles any message. Standard KEDA autoscaling.
- **Split-key storage**: Each slice writes to its own S3 object. No read-modify-write, no contention, no CAS.
- **State proxy**: Aggregator accesses S3 through transparent filesystem emulation (epic 1dmf). Handler uses standard Python file I/O.
- **Stateless Deployment**: No PVCs, no StatefulSets, no shard affinity. State lives in S3.
- **Protocol-level extensibility**: The `x-asya-fan-in` header and message format are fixed. Different aggregator backends plug in as handler modules.

---

## Architecture Decision Records

### ADR-1: Split-Key Pattern on External Storage (Not Embedded Database)

**Context**: The aggregator needs durable storage for in-flight fan-in state. Options considered:

| Option | Pros | Cons |
|--------|------|------|
| Embedded RocksDB per replica | Fast writes, no network | Requires PVCs, shard affinity, scale-down draining. Contradicts stateless Deployment principle (epic 1dmf ADR-6, ADR-7). |
| Redis with CAS counter | Fast, atomic INCR | CAS contention under concurrent writes. Layer 1 retry overwrites other writers' data in multi-writer scenarios. |
| Single-key with CAS | Simple model | Stores all payloads in one KV entry. Size grows with N. CAS contention on every slice arrival. |
| **Split-key on S3** | **Zero contention, arbitrary payload sizes, no CAS, no PVCs** | **S3 latency (~5-50ms per operation)** |

**Decision**: Split-key pattern on S3 via state proxy sidecar.

**How it works**: Each fan-in operation creates a directory of files:

```
/state/fanin/{origin_id}/
+-- message.json        <-- route + headers for merged envelope (~500 bytes)
+-- slice-0.json        <-- parent payload (index 0)
+-- slice-1.json        <-- sub-agent result 1
+-- slice-N.json        <-- sub-agent result N
+-- complete            <-- sentinel: atomic create-if-not-exists
```

**Why zero contention**:
- Each slice writes to its own unique key (`slice-{idx}.json`) -- no two pods ever write the same key
- Completeness is detected by listing the directory (`os.listdir`) -- read-only operation
- Exactly-once emission uses atomic create of `complete` sentinel (`open(path, "xb")`) -- not CAS, just create-if-not-exists
- No counters, no read-modify-write, no retries

**Rationale**:
- **Aligns with epic 1dmf**: Stateless Deployment + external state via state proxy. No PVCs, no StatefulSets, no shard affinity. Same architecture as all other stateful actors.
- **S3 latency is acceptable**: Sub-agents take seconds (LLM inference). S3 operations at ~5-50ms are negligible.
- **Payload size is not a concern**: Each slice is its own S3 object. No aggregation until emission. S3 handles objects up to 5GB.
- **S3 strong consistency**: Since December 2020, S3 provides strong read-after-write consistency. `listdir` after a successful write always sees the written object.
- **TTL via S3 lifecycle policies**: Stale aggregation state (partial failures) is automatically cleaned up by S3 lifecycle rules. No background threads needed.

**Consequences**:
- Requires `open(path, "x")` mode support in `asya_runtime.py` (exclusive create maps to `PUT /keys/{key}` with `If-None-Match: *`)
- On emission, the aggregator reads N+1 slice files sequentially. For large N (100+ slices), this could be optimized with parallel reads in a future version.

### ADR-2: Generated Fan-Out Router (Simplified, No Inline Sharding)

**Context**: The compiled route says `"aggregator"` and messages must reach the aggregator queue. The fan-out router splits the input into N slices and emits N+1 messages with fan-in headers. Without sharding, no shard resolution is needed.

**Decision**: The fan-out router is a **compiler-generated router** that handles slicing logic. Sharding is **opt-in** via the `ASYA_FANIN_SHARDS` env var (default: 1 = no sharding).

**Default behavior (ASYA_FANIN_SHARDS=1)**:
- No sharding. Messages route to `"aggregator"` directly.
- No `x-asya-route-override` header for fan-in.
- No xxhash dependency.

**Sharding behavior (ASYA_FANIN_SHARDS > 1)** (future extensibility):
- Router computes shard via rendezvous hashing: `aggregator-{shard}`.
- Stamps `x-asya-route-override: {"aggregator": "aggregator-{shard}"}`.
- Requires `xxhash` dependency.
- Used with sharded aggregator flavors (see [Extensibility](#extensibility)).

**Generated router structure** (default, no sharding):

```python
import json
import os

_FANIN_SHARDS = int(os.environ.get("ASYA_FANIN_SHARDS", "1"))

if _FANIN_SHARDS > 1:
    import xxhash

    def _resolve_aggregator(origin_id, target):
        best = max(range(_FANIN_SHARDS),
                   key=lambda i: xxhash.xxh64_intdigest(
                       f"{origin_id}:{i}".encode()))
        shard = f"{target}-{best}"
        return shard, {"x-asya-route-override": {target: shard}}
else:
    def _resolve_aggregator(origin_id, target):
        return target, {}


def fanout_research_flow_L2(message):
    p = message["payload"]
    r = message["route"]
    c = r["current"]
    origin_id = message["id"]
    _agg_abstract = r["actors"][c + 1]
    _agg, _override = _resolve_aggregator(origin_id, _agg_abstract)
    _hdrs = message.get("headers", {})

    # --- Accumulate: DSL loop as-is, actor call -> (name, payload) ---
    _slices = []
    for t in p["topics"]:
        _slices.append((resolve("research_agent"), t))
    # ---

    _n = len(_slices) + 1
    _fan_in = {"actor": _agg_abstract, "origin_id": origin_id,
               "slice_count": _n, "aggregation_key": "/results"}

    # Index 0: parent payload (first yield -> keeps original message.id)
    yield {
        "route": {"actors": list(r["actors"]), "current": c + 1},
        "headers": {**_hdrs, **_override,
                    "x-asya-fan-in": {**_fan_in, "slice_index": 0}},
        "payload": json.loads(json.dumps(p)),
    }

    # Indices 1..N: sub-agent slices
    for _i, (_actor, _payload) in enumerate(_slices):
        yield {
            "route": {"actors": [_actor, _agg], "current": 0},
            "headers": {**_hdrs, **_override,
                        "x-asya-fan-in": {**_fan_in, "slice_index": _i + 1}},
            "payload": _payload,
        }
```

**Rationale**:
- **No extra hop**: The fan-out router IS the splitting actor. No separate shard-resolver.
- **Handles all patterns**: The DSL loop/list is copied verbatim into the generated code.
- **Sharding is opt-in**: Default is no sharding. Set `ASYA_FANIN_SHARDS > 1` to enable. Algorithm changes require regenerating the router.
- **Leverages existing infrastructure**: When sharding is enabled, the `x-asya-route-override` header from the A/B Routing RFC (epic 1crb) provides the resolution mechanism.

### ADR-3: `origin_id` as Aggregation Key

**Context**: The aggregator needs a stable key to group all messages belonging to the same fan-out operation, and it needs to know what `id` to assign to the merged envelope. Using `parent_id` (set by the sidecar's generator fanout mechanism) was rejected because it is fragile through envelope-mode sub-agent hops and couples fan-in to sidecar internals.

**Decision**: The fan-out router reads the incoming `message.id`, stores it as `origin_id` in the `x-asya-fan-in` header on all emitted messages (parent payload + slices), and uses it for two purposes:

1. **Aggregation key** in storage (S3 directory name: `/state/fanin/{origin_id}/`)
2. **Merged envelope ID** -- restored on the merged envelope so downstream actors see the same message identity

**Rationale**:

- **`message.id` is internal**: The `message.id` field is a unique identifier of the message object itself. It is managed by the sidecar (kept on first yield, new UUID on subsequent yields) and is not used in any aggregation, routing, or tracking logic. Gateway tracking uses separate headers (`x-asya-task-id`, `x-asya-request-id`). The `message.id` field exists solely for message-level deduplication and debugging.
- **Decoupled from sidecar ID assignment**: The aggregator reads `origin_id` from `x-asya-fan-in`, not from `message.id` or `x-asya-parent-id`. Sidecar ID assignment rules have zero impact on fan-in.
- **Survives arbitrary sub-agent hops**: The `x-asya-fan-in` header is part of `headers`, which is preserved by the runtime in both payload and envelope modes.
- **Unique per fan-out**: Each incoming message has a unique `message.id` (UUID). Sequential fan-outs don't collide because the aggregator deletes the state after emitting the merged envelope.
- **Retry-idempotent**: If the fan-out router crashes and the message is redelivered (same `message.id`), the same `origin_id` produces the same aggregation key -- no orphaned state.

### ADR-4: Atomic Create for Exactly-Once Emission

**Context**: When the last slice arrives and completeness is detected, the aggregator must emit exactly one merged envelope. With multiple pods processing slices concurrently, two pods could detect completeness simultaneously.

**Decision**: Use `open(path, "xb")` (Python exclusive create) to create a `complete` sentinel file. Only one pod succeeds; the other gets `FileExistsError` and returns `None`.

**How it maps to S3**: Python's `"x"` mode maps to `PUT /keys/{key}` with `If-None-Match: *` (create-if-not-exists). S3 supports this natively since August 2024. Only one writer succeeds; the other gets 412 Precondition Failed, which the runtime translates to `FileExistsError`.

**Why not CAS**: This is simpler than CAS. There is no read-modify-write cycle. It's a single atomic write with a precondition. No retries, no contention, no revision tracking.

**Runtime requirement**: `asya_runtime.py` must support `"x"` and `"xb"` open modes, translating them to conditional PUT requests. This is a small addition (~5 lines) to the interception layer.

---

## Fan-In Protocol

### Message ID Semantics

Fan-in is **fully abstract from message identity**. The aggregator never inspects `message.id` -- it is an internal unique identifier of the message object, managed by the sidecar, and not used in any aggregation or routing logic.

The fan-in protocol carries all needed identifiers in its own `x-asya-fan-in` header:

- **`origin_id`**: The original `message.id` before fan-out. Serves two roles: aggregation key (S3 directory name) and the `id` restored on the merged envelope. Set by the fan-out router (it reads `message.id` before yielding). See ADR-3.

Other identity headers that may be present on messages are **orthogonal** to fan-in:

- **`x-asya-parent-id`** (set by sidecar): Links a yielded message to its originator. Tracing/debugging only -- not used in logic. Set on 2nd+ yields (see "Yield Order" below).
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

**Fire-and-forget semantics**: Yield-only fan-out (without fan-in) is fire-and-forget. Only the first message (index 0) is tracked by the gateway -- it keeps the original `message.id`, so SSE streaming and task tracking continue to work. Subsequent yields (index > 0, `parent_id` set) are side effects that proceed independently. When they reach x-sink, they are acked silently without gateway reporting (see [Non-Reporting Mechanisms](#non-reporting-mechanisms-in-x-sink-and-x-sump)).

**Nested fan-out tracing**: When a fan-out child itself fans out, `parent_id` only links to the immediate parent. To trace back to the ultimate root across arbitrary depth, use `root_id = root_id or parent_id` -- if a `root_id` already exists (from a prior fan-out), preserve it; otherwise derive it from `parent_id`. This should live in a header (`x-asya-root-id`). See rfc-actor-states.md (rfc0 branch) for full analysis.

### Addressed Fan-In

The `x-asya-fan-in` header is **transient**: it exists only on messages between the fan-out router and the aggregator. The fan-out router stamps it at emission time; the aggregator reads it and strips it from the merged envelope before emitting to the continuation actor. Outside of the fan-out/fan-in segment of the pipeline, this header is not present.

The header includes an `actor` field that identifies the target aggregator actor. The aggregator checks `x-asya-fan-in.actor == ASYA_ACTOR_NAME` to confirm the header is addressed to it.

The `origin_id` (original `message.id`) serves as the aggregation key. It is stamped into every `x-asya-fan-in` header and is used as the S3 directory name (`/state/fanin/{origin_id}/`). This decouples aggregation from sidecar ID assignment entirely (see ADR-3).

For sequential fan-outs in the same flow, each fan-out has a different `origin_id` because the aggregator deletes the state after emitting, and the next fan-out receives a merged envelope (with the restored `origin_id` as its `message.id`):

```python
def multi_fanout(p: dict) -> dict:
    # Fan-out 1: origin_id = message.id of incoming envelope
    p["research"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
    # Fan-out 2: origin_id = message.id of merged envelope from fan-out 1
    #            (same value, but state was deleted after fan-out 1 completed)
    p["reviews"] = [review_agent(p["research"][i]) for i in range(len(p["research"]))]
    return p
```

### Unified Message Schema

All fan-in messages (parent payload and sub-agent slices) share the same `x-asya-fan-in` header schema. There is no `type` discriminator -- the aggregator distinguishes the parent payload by `slice_index == 0`.

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
| `origin_id` | Original `message.id` before fan-out. Used as aggregation key (S3 directory) and `id` of the merged envelope (see ADR-3). |
| `slice_index` | Position in the results array. `0` = parent payload (original payload + continuation route), `1..N` = sub-agent results. |
| `slice_count` | Total messages expected: N sub-agent slices + 1 parent payload. |
| `aggregation_key` | RFC 6901 JSON Pointer into the parent payload where the sub-agent results list is placed (e.g., `/results`). Present on all messages for schema uniformity. |

---

## Aggregator Actor Design

### v0: S3 Split-Key Handler

The aggregator is a crew actor running in envelope mode. It stores state in S3 via the state proxy sidecar.

**Storage layout** per fan-in operation:

```
/state/fanin/{origin_id}/
+-- message.json        <-- continuation metadata (route, headers, id)
+-- slice-0.json        <-- parent payload (index 0)
+-- slice-1.json        <-- sub-agent result 1
+-- slice-N.json        <-- sub-agent result N
+-- complete            <-- emission lock (atomic create sentinel)
```

```python
import json
import os

import jsonpointer

_TRANSIENT_HEADERS = {
    "x-asya-fan-in", "x-asya-route-override",
    "x-asya-route-resolved", "x-asya-parent-id",
}


def aggregator(envelope: dict) -> dict | None:
    fan_in = envelope["headers"]["x-asya-fan-in"]
    origin_id = fan_in["origin_id"]
    idx = fan_in["slice_index"]
    base = f"/state/fanin/{origin_id}"

    # 1. Write slice (unique key per slice, no contention)
    slice_path = f"{base}/slice-{idx}.json"
    if not os.path.exists(slice_path):
        with open(slice_path, "w") as f:
            json.dump(envelope["payload"], f)

    # 2. Index 0: save continuation metadata (written once)
    if idx == 0:
        msg_path = f"{base}/message.json"
        if not os.path.exists(msg_path):
            route = envelope["route"].copy()
            route["current"] += 1
            msg_meta = {
                "id": origin_id,
                "route": route,
                "headers": {k: v for k, v in
                            envelope.get("headers", {}).items()
                            if k not in _TRANSIENT_HEADERS},
            }
            with open(msg_path, "w") as f:
                json.dump(msg_meta, f)

    # 3. Check completeness via listing
    entries = os.listdir(base)
    slice_files = sorted(e for e in entries if e.startswith("slice-"))

    if len(slice_files) < fan_in["slice_count"]:
        return None  # still accumulating

    # 4. Exactly-once emission lock
    try:
        with open(f"{base}/complete", "xb") as f:
            f.write(b"1")
    except FileExistsError:
        return None  # another pod already emitting

    # 5. Read all slices and merge
    with open(f"{base}/message.json") as f:
        msg = json.load(f)

    results = []
    for sf in slice_files:
        with open(f"{base}/{sf}") as f:
            results.append(json.load(f))

    msg["payload"] = results[0]  # parent payload as base
    jsonpointer.set_pointer(msg["payload"],
                            fan_in["aggregation_key"],
                            results[1:])

    # 6. Cleanup
    for entry in os.listdir(base):
        os.remove(f"{base}/{entry}")

    return msg
```

### Behavior

- **Zero contention**: Each slice writes to `slice-{idx}.json` -- unique key per slice. No two pods write the same key. No CAS, no retries.
- **Idempotency**: `os.path.exists(slice_path)` check prevents duplicate writes. A redelivered message (at-least-once) is safely ignored.
- **Ordering**: Results are placed at `results[slice_index]`, preserving DSL order regardless of arrival order. On emission, `results[0]` becomes the base payload and `results[1:]` is placed at `aggregation_key`.
- **Index 0 before slices**: If sub-agent slices arrive before the parent payload (index 0), they write their slice files. When index 0 arrives, it writes `message.json`. Completeness check still works -- it only counts slice files.
- **Multiple fan-ins**: Each fan-out uses a different `origin_id` (unique `message.id`). Sequential fan-outs don't collide because the state directory is cleaned up after emitting.

### Non-Reporting Mechanisms in x-sink and x-sump

When the aggregator returns `None` (still accumulating), the sidecar acks the message and routes it to x-sink with `status.phase = "succeeded"` (the sidecar always overwrites the phase). Without special handling, x-sink would report a false "finished" status to the gateway.

x-sink and x-sump use **three independent mechanisms** to suppress gateway reporting, evaluated in this order:

#### 1. `x-asya-fan-in` header detection

- **When**: Message has `x-asya-fan-in` header -- it's a partial fan-in result
- **x-sink**: Ack and consume. Persist to S3 if configured, run hooks if configured. Do NOT report to gateway.
- **x-sump**: Log the error, persist to S3 if configured. Do NOT report to gateway. The aggregator will detect the incomplete fan-out via TTL cleanup.
- **Why checked first**: Fan-in index 0 (parent payload) has NO `parent_id` but must still be suppressed. The `x-asya-fan-in` header is the only reliable signal.

The `x-asya-fan-in` header is already on the message because it was stamped by the fan-out router and preserved through the aggregator. This requires no sidecar changes.

#### 2. `parent_id` detection (fire-and-forget yield children)

- **When**: Message has `parent_id` set and NO `x-asya-fan-in` header -- it's a fire-and-forget yield child
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
| 1 | `x-asya-fan-in` header present | configurable | no |
| 2 | `parent_id` set (no fan-in header) | configurable | no |
| 3 | Non-terminal `status.phase` | yes | no |
| -- | None of the above | yes | yes |

`ASYA_SINK_FANOUT_HOOKS` (default: `false`) -- when `false`, hooks are skipped for messages with `parent_id` set (fire-and-forget children). Set to `true` to run hooks on every fan-out child.

Mechanisms 1 and 2 work today (signals are already set by the fan-out router and sidecar). Mechanism 3 requires sidecar changes (asya-0bvg). See rfc-actor-states.md (rfc0 branch) for the full phase lifecycle analysis.

---

## Deployment

### Aggregator Deployment

A single aggregator Deployment with state proxy sidecar for S3 access:

```yaml
apiVersion: asya.dev/v1alpha1
kind: AsyncActor
metadata:
  name: aggregator
spec:
  image: asya-crew:latest
  handler: asya_crew.fanin.s3_split_key.aggregator
  handlerMode: envelope
  transport: sqs
  stateProxy:
    - name: fanin
      mount:
        path: /state/fanin
      connector:
        image: asya-bridges/state-proxy/s3-buffered-lww:latest
        env:
          - name: STATE_BUCKET
            value: "fanin-state"
          - name: STATE_PREFIX
            value: "v1/"
          - name: AWS_REGION
            value: "us-east-1"
```

**Note**: Uses `s3-buffered-lww` (last-write-wins), not CAS. Each key is written once (no conflicts). The `complete` sentinel uses atomic create (`If-None-Match: *`), which is handled at the HTTP protocol level, not as a CAS connector feature.

### Queue Naming

Single aggregator queue: `asya-{namespace}-aggregator`

For sharded flavors (future), each shard gets its own queue: `asya-{namespace}-aggregator-0`, `asya-{namespace}-aggregator-1`, etc.

### Fan-Out Router Deployment

The fan-out router is a compiler-generated actor. It uses the generated `routers.py` module:

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
    - name: ASYA_HANDLER_RESEARCH_AGENT
      value: "research-agent"           # actor name resolution
    # ASYA_FANIN_SHARDS not set -> defaults to 1 (no sharding)
```

---

## Scaling Behavior

### Standard KEDA Autoscaling

The aggregator uses standard KEDA autoscaling on queue depth. No shards, no draining, no shard count configuration.

- **Scale up**: More pods process messages from the same queue. Each pod accesses the same S3 bucket. No coordination needed.
- **Scale down**: Standard pod termination. In-flight messages return to queue and are processed by remaining pods. State is in S3, not on the pod.
- **Scale to zero**: When queue is empty, KEDA scales to 0. State persists in S3.

### Fan-Out Atomicity

If the fan-out router crashes mid-emission (after emitting some messages but not all), a partial fan-out occurs. The aggregator will wait indefinitely for missing slices.

**Mitigation**: S3 lifecycle policies. Aggregation state directories older than a configurable timeout (e.g., 1 hour) are automatically deleted by S3. The original message is nacked (if transport supports it) or sent to error-end.

This is an orthogonal concern that applies regardless of the aggregator backend.

---

## Extensibility

The fan-in architecture separates **protocol** from **implementation**. The protocol (headers, message format, yield order) is fixed. The implementation (how state is stored, how completeness is detected) is a **flavor** — a pluggable handler module within `asya-crew`.

### Two Flavor Categories

Flavors fall into two categories based on whether they need shard affinity:

**Non-sharded flavors** (stateless Deployment, standard KEDA):
- State lives in an external store accessed via state proxy sidecar
- Any pod handles any message — no routing constraints
- `ASYA_FANIN_SHARDS=1` (default) — fan-out router does not stamp `x-asya-route-override`

**Sharded flavors** (StatefulSet or per-shard Deployments, per-shard queues):
- State lives locally on the pod (embedded DB + PVC) or in a sharded external store
- All messages for the same `origin_id` must reach the same shard
- `ASYA_FANIN_SHARDS > 1` — fan-out router computes rendezvous hash, stamps `x-asya-route-override`
- Requires scale-down draining (see `adr.rejected.rendezvous-sharding-rocksdb.md`)

### Extension Point 1: Aggregator Handler Flavors

Each flavor is a handler module in `src/asya-crew/asya_crew/fanin/`. The handler is specified via `ASYA_HANDLER` on the AsyncActor spec.

**Non-sharded flavors** (external state, no affinity):

| Flavor | Handler | Backend | Completeness | When to use |
|--------|---------|---------|-------------|-------------|
| **fanin-s3** (v0) | `asya_crew.fanin.s3_split_key.aggregator` | S3 via state proxy (`s3-buffered-lww`) | `listdir` + sentinel | Default. Zero contention, handles large payloads, S3 lifecycle for TTL. |
| fanin-redis (planned) | `asya_crew.fanin.redis_split_key.aggregator` | Redis via state proxy (`redis-buffered-lww`) | `listdir` + sentinel | Low-latency fan-in. Same split-key pattern but sub-ms reads. |
| fanin-postgres (planned) | `asya_crew.fanin.postgres.aggregator` | PostgreSQL via state proxy | SQL count query | When PostgreSQL is already in the stack. ACID transactions for completeness. |

**Sharded flavors** (local state, shard affinity):

| Flavor | Handler | Backend | Completeness | When to use |
|--------|---------|---------|-------------|-------------|
| fanin-rocksdb-sharded (planned) | `asya_crew.fanin.rocksdb_sharded.aggregator` | Embedded RocksDB on PVC | In-memory counter | Ultra-high throughput, zero network latency. Requires PVCs + `ASYA_FANIN_SHARDS > 1`. |
| fanin-natskv-sharded (planned) | `asya_crew.fanin.natskv_sharded.aggregator` | NATS KV (local to shard) | KV revision counter | When NATS is the transport. Revision-based CAS for concurrency within shard. |

All flavors:
- Receive the same envelope with the same `x-asya-fan-in` header
- Return the same merged envelope format (or `None` when accumulating)
- Use the same fan-in protocol
- Live in `asya-crew` as a module under `asya_crew.fanin.<flavor>`

The fan-out router does not know which flavor the aggregator uses. It stamps fan-in headers and emits messages. Sharding (if needed) is the only deployment-time coupling between the router and the aggregator.

### Extension Point 2: Fan-Out Router Sharding

Sharding is controlled by the `ASYA_FANIN_SHARDS` env var on the fan-out router:

| Value | Behavior | Used with |
|-------|----------|-----------|
| `1` (default) | No sharding. Messages route to `"aggregator"` directly. | All non-sharded flavors |
| `> 1` | Rendezvous hashing. Stamps `x-asya-route-override`. | Sharded flavors (each shard has own queue) |

Sharding is an opt-in deployment decision. The code generator always emits the `_resolve_aggregator()` function, which is a no-op when `ASYA_FANIN_SHARDS=1`.

When `ASYA_FANIN_SHARDS > 1`:
- Requires `xxhash` dependency for rendezvous hashing
- Each shard is a separate AsyncActor deployment: `aggregator-0`, `aggregator-1`, etc.
- Scale-down requires draining (see `adr.rejected.rendezvous-sharding-rocksdb.md`)

### Flavor Compatibility Matrix

| Flavor | Category | Sharding | State proxy | PVC | CAS |
|--------|----------|----------|-------------|-----|-----|
| fanin-s3 (v0) | Non-sharded | `SHARDS=1` | `s3-buffered-lww` | No | No |
| fanin-redis | Non-sharded | `SHARDS=1` | `redis-buffered-lww` | No | No |
| fanin-postgres | Non-sharded | `SHARDS=1` | postgres connector | No | No (ACID) |
| fanin-rocksdb-sharded | Sharded | `SHARDS>1` | None (embedded) | Yes | No (affinity) |
| fanin-natskv-sharded | Sharded | `SHARDS>1` | None (embedded) | Yes | No (affinity) |

### Adding a New Flavor

1. Implement a handler module in `src/asya-crew/asya_crew/fanin/<flavor>/`
2. The handler receives envelopes with `x-asya-fan-in` header
3. The handler returns a merged envelope (or `None` when accumulating)
4. Deploy with the appropriate `ASYA_HANDLER`, `stateProxy` (if non-sharded), and `ASYA_FANIN_SHARDS` (if sharded)

No changes to the fan-out router, the fan-in protocol, or the sidecar.

### Historical Context

The sharded RocksDB approach was the original design before the Semi-Stateful
Actors RFC (epic 1dmf) established the state proxy pattern. The full design
exploration and rejection rationale are preserved in:
- `adr.rejected.rendezvous-sharding-rocksdb.md` — Sharded RocksDB with rendezvous hashing
- `adr.rejected.placement-directory.md` — Placement directory for shard affinity
- `adr.rejected.single-key-cas.md` — Single-key CAS counter approach

---

## Integration with A/B Routing

The fan-in sharding mechanism (when `ASYA_FANIN_SHARDS > 1`) reuses the `x-asya-route-override` header from the A/B Routing RFC (epic 1crb). This is explicitly listed as Use Case 4 in that RFC.

The integration is clean:

- Fan-out router stamps `x-asya-route-override: {"aggregator": "aggregator-2"}` (only when sharding)
- Sidecar at routing time performs a dictionary lookup (existing Layer 1 mechanism)
- Route still says `"aggregator"` (business logic preserved)
- `x-asya-route-resolved` header provides audit trail

A/B testing and fan-in sharding can coexist in the same pipeline:

```json
{
  "x-asya-route-override": {
    "research_agent": "research_agent_v2",
    "aggregator": "aggregator-1"
  }
}
```

In v0 (no sharding), `x-asya-route-override` is not used for fan-in. A/B routing on sub-agents still works independently.

---

## Observability

### Fan-Out Router Metrics

Emitted by the generated fan-out router. Since the router is generated code, the code generator emits OTel instrumentation alongside the routing logic.

| Metric | Type | Description |
|---|---|---|
| `asya.fanout.operations` | Counter | Fan-out operations initiated (one per incoming message) |
| `asya.fanout.slices` | Histogram | Number of sub-agent slices per fan-out operation. Detects unexpectedly large fan-outs. |

**Labels**: `flow` (flow name), `aggregator` (target aggregator actor name).

### Aggregator Metrics

Emitted by the aggregator handler.

| Metric | Type | Description |
|---|---|---|
| `asya.fanin.active` | UpDownCounter | In-flight aggregations (incremented on first slice for a new `origin_id`, decremented on completion or TTL cleanup) |
| `asya.fanin.messages.received` | Counter | Total messages received (parent payloads + sub-agent slices) |
| `asya.fanin.completions` | Counter | Completed aggregations (all slices arrived, merged envelope emitted) |
| `asya.fanin.duration_seconds` | Histogram | Wall-clock time from first slice arrival to completion |
| `asya.fanin.stale_cleanups` | Counter | Aggregation entries expired by TTL (partial fan-out failures) |

**Labels**: `aggregator` (actor name).

Backend-specific storage metrics (S3 request counts, latency) are handled by the state proxy sidecar, not the aggregator handler.

### Backpressure and Alerting

| Alert | Condition | Severity |
|---|---|---|
| AggregatorStaleFanouts | `asya.fanin.active` growing without `asya.fanin.completions` increasing | Warning |
| FanoutCardinalityHigh | `asya.fanout.slices` p99 > 1000 | Warning |

---

## Flow DSL Examples and Code Generation

The Flow DSL supports fan-out via list comprehensions (homogeneous -- same actor, different data) and list literals (heterogeneous -- different actors). Both compile to the same N+1 message protocol using a single code generation strategy.

### Three Syntax Levels

The DSL supports three syntax levels for fan-out. All compile to the **same** distributed fan-out/fan-in -- the difference is only in local execution semantics:

| Syntax | Local Execution | Compiled (Asya) | Flow Type |
|---|---|---|---|
| `[actor(x) for x in items]` | Sequential (sync) | Parallel fan-out (compiler optimization) | `def` |
| `[await actor(x) for x in items]` | Sequential (async, one at a time) | Parallel fan-out (compiler optimization) | `async def` |
| `await asyncio.gather(*(actor(x) for x in items))` | Parallel (async, concurrent) | Parallel fan-out | `async def` |

**Compiler optimization**: List comprehensions with actor calls have no data dependencies between iterations. The compiler automatically promotes them to parallel fan-out on Asya -- even though they run sequentially locally. This is analogous to how a C compiler can auto-vectorize a loop.

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

**Generated router** (simplified, no sharding):

```python
def fanout_research_flow_L2(message):
    p = message["payload"]
    r = message["route"]
    c = r["current"]
    origin_id = message["id"]
    _agg = r["actors"][c + 1]
    _hdrs = message.get("headers", {})

    # --- Accumulate: DSL loop as-is ---
    _slices = []
    for t in p["topics"]:
        _slices.append((resolve("research_agent"), t))

    _n = len(_slices) + 1
    _fan_in = {"actor": _agg, "origin_id": origin_id,
               "slice_count": _n, "aggregation_key": "/results"}

    # Index 0: parent payload
    yield {
        "route": {"actors": list(r["actors"]), "current": c + 1},
        "headers": {**_hdrs,
                    "x-asya-fan-in": {**_fan_in, "slice_index": 0}},
        "payload": json.loads(json.dumps(p)),
    }

    # Indices 1..N: sub-agent slices
    for _i, (_actor, _payload) in enumerate(_slices):
        yield {
            "route": {"actors": [_actor, _agg], "current": 0},
            "headers": {**_hdrs,
                        "x-asya-fan-in": {**_fan_in, "slice_index": _i + 1}},
            "payload": _payload,
        }
```

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

**Generated `_slices` block** (only this part differs):

```python
    _slices = [
        (resolve("sentiment_analyzer"), p["text"]),
        (resolve("topic_extractor"),    p["text"]),
        (resolve("entity_recognizer"),  p["text"]),
    ]
```

The emission boilerplate is identical.

---

## Open Questions

### 1. Exclusive Create Support in Runtime

The aggregator requires `open(path, "x")` mode in `asya_runtime.py`. This maps to `PUT /keys/{key}` with `If-None-Match: *`. The state proxy connector must honor this conditional header and return 412 (mapped to `FileExistsError`) if the key exists.

This is a small addition (~5 lines) to the runtime's mode-switching logic and requires all state proxy connectors to support the `If-None-Match: *` header.

### 2. Header Syntax Constraints for Transport Compatibility

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
| `x-asya-fan-in` | Fan-out router | `{"actor":"...","origin_id":"uuid",...}` (~150 bytes) |
| `x-asya-parent-id` | Sidecar (yield) | UUID string (~36 bytes) |
| `x-asya-task-id` | Gateway | UUID string (~36 bytes) |
| `x-asya-experiment` | Experiment router | String (~30 bytes) |
| `x-asya-variant` | Experiment router | String (~30 bytes) |
| | | **7 of 10 SQS slots** |

This leaves 3 slots for user-defined headers.

### 3. Nested Fan-Out

Can a sub-agent itself fan-out? This creates a tree of aggregations. The current design supports this because:

- Each fan-out uses the incoming `message.id` as `origin_id`
- Nested fan-outs receive different `message.id` values (sidecar assigns new UUIDs to yielded slices)
- Each aggregation is independent

However, the continuation route for a nested fan-out must correctly point back to the outer aggregator. This requires the inner fan-out router to preserve the outer route context. Design deferred until the use case is validated.

### 4. Partial Failure Semantics

What happens when some sub-agent slices succeed and others fail (routed to x-sump)?

- **All-or-nothing** (v0): Aggregator waits for all N slices. If any fail, S3 lifecycle policy eventually expires the incomplete aggregation state.
- **Best-effort** (future): Aggregator emits partial results after timeout, filling failed slots with `null` or an error marker.
- **`return_exceptions` mode** (future, inspired by `asyncio.gather(return_exceptions=True)`): Failed slices are represented as error objects in the results list.

Current design is all-or-nothing. Best-effort and `return_exceptions` modes would require the aggregator to track per-slice failure status and a mechanism for x-sump to notify the aggregator that a slice has permanently failed.

### 5. Gateway Tracking Headers

For A2A and MCP use-cases, the gateway needs to track the status of user-initiated requests across the actor mesh. The gateway sets a tracking header on the initial message:

- **`x-asya-task-id`**: Set by gateway for A2A tasks.
- **`x-asya-request-id`**: Set by gateway for MCP tool calls.

These headers are **orthogonal to fan-in**. The aggregator preserves them on the merged envelope (they are not stripped), so status reporting continues correctly after fan-out/fan-in.

---

## Runtime Enhancement: `open(path, "x")` Mode

The aggregator's exactly-once emission requires `open(path, "xb")` (exclusive create). This is a new capability needed in `asya_runtime.py`:

| Python mode | Behavior | State proxy mapping |
|-------------|----------|---------------------|
| `"x"`, `"xb"` | Create file, fail if exists | `PUT /keys/{key}` with `If-None-Match: *` header |
| `"xt"` | Same as `"x"` but text mode | Same, with text encoding |

**Connector support**: All state proxy connectors must handle the `If-None-Match: *` header on write requests:
- If key does not exist: create and return 200/204
- If key exists: return 412 Precondition Failed

**Runtime translation**: 412 maps to `FileExistsError`, matching Python's `open(path, "x")` behavior when the file already exists.

**Implementation**: ~5 lines in the runtime's mode-switching logic within `_open_write()`.

---

## RFC References

- A/B Routing RFC (epic 1crb) -- `x-asya-route-override` header mechanism
- Semi-Stateful Actors RFC (epic 1dmf) -- State proxy architecture, ADR-6 (Stateless Deployment), ADR-9 (Fan-in as crew actor)
- [JSON Pointer (RFC 6901)](https://www.rfc-editor.org/rfc/rfc6901) -- Standard for addressing values within JSON documents
- [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) -- Python implementation of JSON Pointer (zero dependencies)
- [xxHash](https://xxhash.com/) -- Non-cryptographic hash function (only needed when ASYA_FANIN_SHARDS > 1)
