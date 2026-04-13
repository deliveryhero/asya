---
title: "Flow DSL: fan-out list comprehension and list literal parser"
status: merged
priority: 2
parent: 00000
---

## Summary

Extend the Flow DSL parser to recognize fan-out patterns (list comprehensions and list literals with actor calls) and produce `FanOutCall` IR nodes.

## Supported Patterns

### List Comprehension (homogeneous fan-out)
```python
p["results"] = [research_agent(t) for t in p["topics"]]
p["results"] = [research_agent(p["topics"][i]) for i in range(len(p["topics"]))]
p["results"] = [research_agent(p["query"]) for _ in range(10)]
```

### List Literal (heterogeneous fan-out)
```python
p["result"] = [sentiment_analyzer(p["text"]), topic_extractor(p["text"]), entity_recognizer(p["text"])]
```

### Async variants (same IR output)
```python
p["results"] = [await research_agent(t) for t in p["topics"]]
p["results"] = await asyncio.gather(*(research_agent(t) for t in p["topics"]))
p["results"] = await asyncio.gather(a(x), b(y), c(z))
```

## IR Node

```python
@dataclass
class FanOutCall:
    target_key: str           # JSON Pointer, e.g. "/results"
    slices: list[SliceSpec]   # list of (actor_name, payload_expr) from comprehension/literal
    iterator: IteratorSpec    # for comprehension: variable, iterable expr
    line: int                 # source line number
```

## Changes

### `src/asya-cli/asya_cli/flow/parser.py`
- Detect `p["key"] = [actor(x) for x in items]` (ListComp with actor call)
- Detect `p["key"] = [actor1(x), actor2(y)]` (List with actor calls)
- Detect `p["key"] = await asyncio.gather(...)` (async fan-out)
- Validate: all list elements must be actor calls (no mixing mutations and calls)
- Validate: assignment target must be payload subscript (for aggregation_key)
- Produce `FanOutCall` operation in the operations list

### Tests
- Parse list comprehension with `for x in items`
- Parse list comprehension with `for i in range(len(...))`
- Parse list comprehension with `for _ in range(N)` (fixed count)
- Parse list literal with multiple actor calls
- Parse async variants (await in comprehension, asyncio.gather)
- Error: mixed actor calls and non-calls in list
- Error: list comprehension without actor call
- Error: nested list comprehensions (not supported yet)

## References
- RFC: docs/rfc/fan-in/rfc-fan-in.md (Flow DSL Examples and Code Generation)
- RFC: docs/rfc/fan-in/rfc-fan-in.md (All Supported Patterns)


---
_Migrated from beads `asya-pmor`_
