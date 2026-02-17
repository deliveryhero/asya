---
title: "Flow DSL: fan-out router code generator"
status: open
priority: 2 # medium
type: task
---

## Summary

Extend the Flow DSL code generator to produce fan-out router Python code from `FanOutCall` IR nodes. The generated router emits N+1 messages (1 parent payload + N sub-agent slices) with inline rendezvous sharding.

## Generated Code Structure

```python
import xxhash

_FANIN_SHARDS = int(os.environ.get("ASYA_FANIN_SHARDS", "1"))

def _rendezvous_shard(origin_id, target):
    best = max(range(_FANIN_SHARDS),
               key=lambda i: xxhash.xxh64_intdigest(f"{origin_id}:{i}".encode()))
    return f"{target}-{best}"

def fanout_<flow>_L<line>(message):
    p = message["payload"]
    r = message["route"]
    c = r["current"]
    origin_id = message["id"]
    _agg = r["actors"][c + 1]
    _shard = _rendezvous_shard(origin_id, _agg)
    _hdrs = message.get("headers", {})

    # --- Accumulate: varies per pattern ---
    _slices = []
    for t in p["topics"]:
        _slices.append((resolve("research_agent"), t))
    # ---

    _n = len(_slices) + 1
    _fan_in = {"actor": _agg, "origin_id": origin_id,
               "slice_count": _n, "aggregation_key": "/results"}

    # Index 0: parent payload
    yield { ... }

    # Indices 1..N: sub-agent slices
    for _i, (_actor, _payload) in enumerate(_slices):
        yield { ... }
```

## Changes

### `src/asya-cli/asya_cli/flow/codegen.py`
- Handle `FanOutCall` operation type
- Generate accumulation code based on comprehension type (for-in, range, literal)
- Generate emission boilerplate (index 0 + indices 1..N)
- Generate `_rendezvous_shard()` utility function (once per routers.py, not per router)
- Add `xxhash` import at module level

### `src/asya-cli/asya_cli/flow/grouper.py`
- Fan-out operation creates a new router group (cannot be batched with mutations)
- The router after fan-out is the aggregator (implicit in the route)

### Tests
- Generate code for homogeneous fan-out (list comprehension)
- Generate code for heterogeneous fan-out (list literal)
- Generate code for fixed-count fan-out
- Verify `_rendezvous_shard()` is generated once
- Verify generated code is syntactically valid Python
- Verify generated router yields correct number of messages
- End-to-end: parse -> group -> codegen -> execute generated code with mock message

## Dependencies
- DEPENDS ON: Flow DSL fan-out parser (need FanOutCall IR nodes)

## References
- RFC: docs/rfc/fan-in/rfc-fan-in.md (Code Generation Strategy)
- ADR-2: Generated Fan-Out Router with Inline Sharding


---
_Migrated from beads `asya-q2kp`_
