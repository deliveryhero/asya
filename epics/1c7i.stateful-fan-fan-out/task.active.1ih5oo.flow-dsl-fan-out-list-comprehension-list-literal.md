---
title: "Flow DSL: fan-out list comprehension and list literal parser"
priority: 2 # medium
type: task
tags:
  - worktree:1c7i.stateful-fan-fan-out/1ih5oo.flow-dsl-fan-out-list-comprehension-list-literal
---


## Summary

Parse fan-out syntax (list comprehensions and list literals with actor calls) into `FanOutCall` IR nodes in the Flow DSL parser. This is the prerequisite for the fan-out code generator (1fr7i0) and dot diagram visualization (1froou).

## Supported Syntax

### List comprehension (homogeneous fan-out)
```python
p["results"] = [research_agent(t) for t in p["topics"]]
p["results"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
p["results"] = [research_agent(p["query"]) for _ in range(10)]
```

### List literal (heterogeneous fan-out)
```python
p["result"] = [
    sentiment_analyzer(p["text"]),
    topic_extractor(p["text"]),
    entity_recognizer(p["text"]),
]
```

### asyncio.gather (async fan-out)
```python
p["results"] = await asyncio.gather(*(research_agent(t) for t in items))
p["results"] = await asyncio.gather(a(x), b(y), c(z))
```

## IR Node

```python
@dataclass
class FanOutCall:
    target_key: str              # JSON Pointer, e.g. "/results"
    pattern: str                 # "comprehension" | "literal" | "gather"
    actor_calls: list            # List of (actor_name, payload_expr) or loop spec
    line_number: int             # Source line for generated router naming
```

## Changes

### `src/asya-cli/asya_cli/flow/parser.py`
- Detect list comprehension assignment: `p["key"] = [actor(x) for x in ...]`
- Detect list literal assignment: `p["key"] = [actor1(x), actor2(y), ...]`
- Detect asyncio.gather: `p["key"] = await asyncio.gather(...)`
- Validate: all list elements must be actor calls (not arbitrary expressions)
- Validate: assignment target must be a payload key (for `aggregation_key`)
- Emit `FanOutCall` IR node with all metadata needed by codegen

### Tests
- Parse homogeneous fan-out (for-in comprehension)
- Parse range-based comprehension
- Parse fixed-count comprehension (underscore variable)
- Parse heterogeneous fan-out (list literal)
- Parse asyncio.gather with generator expression
- Parse asyncio.gather with explicit args
- Reject mixed list (actor calls + non-actor expressions)
- Reject nested comprehensions
- Extract correct `aggregation_key` from assignment target
- Verify line number is captured for router naming

## References
- RFC: `.aint/epics/1c7i.stateful-fan-fan-out/rfc.md` (Flow DSL Examples, All Supported Patterns)
