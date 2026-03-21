# Flow Compiler

The Flow Compiler lets you describe multi-actor pipelines as familiar Python
code. The compiler transforms your Python into a flat graph of standard
`AsyncActor` resources — no new abstractions, no Flow CRD, no runtime
dependency.

## Write Python, deploy actors

A flow is a Python function that calls other actors:

```python
async def pipeline(payload):
    enriched = await enrich(payload)
    if enriched["needs_review"]:
        result = await human_review(enriched)
    else:
        result = await auto_process(enriched)
    return await summarize(result)
```

The compiler reads this function and produces a set of router actors that
replicate the control flow using message passing.

## How it works: CPS transformation

The compiler uses **continuation-passing style** (CPS): instead of calling the
next function, each step sends a message to the next actor's queue. Branches
become conditional route rewrites. Sequential calls become chained routes.

The output is a set of standard `AsyncActor` manifests linked by an
`asya.sh/flow` label. There is no Flow CRD — flows are just actors.

## Supported control flow

| Python construct | Mesh equivalent |
|-----------------|-----------------|
| Sequential calls | Chained routes |
| `if/else` | Conditional route rewrite |
| `for x in items` / list comprehension | Fan-out with automatic fan-in |
| `asyncio.gather(a, b)` | Heterogeneous fan-out with aggregation |

## What flows cannot do

Flows enforce 1:1 payload mapping per actor call. These actor-only features are
not available in flows:

- ❌ `yield "FLY", ...` — FLY streaming events
- ❌ Multiple `yield` without aggregation (fire-and-forget fan-out)
- ❌ Returning `None` (abort)

Use standalone actors for these patterns.

## Purely additive

The flow compiler is a build-time tool. It generates standard actors that run on
the standard mesh. Removing the compiler does not affect already-deployed flows.
No runtime component is added.

## Further reading

- [Flow DSL specification](../reference/specs/flow-dsl.md) — syntax rules,
  compilation semantics, edge cases
- [Flow Compiler component](../reference/components/lab-flow-compiler.md) —
  CLI usage, output formats
- [Your first flow](../usage/start-first-flow.md) — step-by-step tutorial
