---
title: "Flow DSL: fan-out router code generator"
status: merged
priority: 2
dependencies:
  - 1ih5b
tags:
  - type:feature
---

## Summary

Extend the Flow DSL code generator to produce fan-out router Python code from `FanOutCall` IR nodes. The generated router emits N+1 messages (1 parent payload + N sub-agent slices) with fan-in headers.

Sharding is **opt-in** via `ASYA_FANIN_SHARDS` env var (default 1 = no sharding). When sharding is disabled, the generated code is simple — no rendezvous hashing, no xxhash dependency.

## Generated Code Structure

### Default (no sharding, ASYA_FANIN_SHARDS=1)

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


def fanout_<flow>_L<line>(message):
    p = message["payload"]
    r = message["route"]
    origin_id = message["id"]
    _agg_abstract = r["next"][0]   # aggregator is first in next list
    _agg, _override = _resolve_aggregator(origin_id, _agg_abstract)
    _hdrs = message.get("headers", {})

    # --- Accumulate: varies per pattern ---
    _slices = []
    for t in p["topics"]:
        _slices.append((resolve("research_agent"), t))
    # ---

    _n = len(_slices) + 1
    _fan_in = {"actor": _agg_abstract, "origin_id": origin_id,
               "slice_count": _n, "aggregation_key": "/results"}

    # Index 0: parent payload
    # Fan-out generators must manually shift the route (runtime does not shift for generators).
    yield {
        "route": {"prev": r["prev"] + [r["curr"]], "curr": r["next"][0], "next": r["next"][1:]},
        "headers": {**_hdrs, **_override,
                    "x-asya-fan-in": {**_fan_in, "slice_index": 0}},
        "payload": json.loads(json.dumps(p)),
    }

    # Indices 1..N: sub-agent slices (new independent routes)
    for _i, (_actor, _payload) in enumerate(_slices):
        yield {
            "route": {"prev": [], "curr": _actor, "next": [_agg]},
            "headers": {**_hdrs, **_override,
                        "x-asya-fan-in": {**_fan_in, "slice_index": _i + 1}},
            "payload": _payload,
        }
```

## Changes

### `src/asya-cli/asya_cli/flow/codegen.py`
- Handle `FanOutCall` operation type
- Generate accumulation code based on comprehension type (for-in, range, literal)
- Generate emission boilerplate (index 0 + indices 1..N)
- Generate `_resolve_aggregator()` function (once per routers.py) with conditional sharding
- Conditional `xxhash` import (only when `ASYA_FANIN_SHARDS > 1` at runtime)

### `src/asya-cli/asya_cli/flow/grouper.py`
- Fan-out operation creates a new router group (cannot be batched with mutations)
- The router after fan-out is the aggregator (implicit in the route)

### Tests
- Generate code for homogeneous fan-out (list comprehension)
- Generate code for heterogeneous fan-out (list literal)
- Generate code for fixed-count fan-out
- Verify `_resolve_aggregator()` is generated once
- Verify generated code is syntactically valid Python
- Verify generated router yields correct number of messages (N+1)
- Verify no `xxhash` import when `ASYA_FANIN_SHARDS=1`
- Verify `x-asya-route-override` is stamped when `ASYA_FANIN_SHARDS > 1`
- End-to-end: parse -> group -> codegen -> execute generated code with mock message

## Dependencies
- DEPENDS ON: Flow DSL fan-out parser (need FanOutCall IR nodes)

## References
- Fan-in RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (Code Generation Strategy, ADR-2)


_Migrated from beads `asya-q2kp`_
