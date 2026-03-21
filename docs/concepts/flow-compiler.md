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

The compiler also generates a visual graph of the compiled pipeline:

<p align="center">
<a href="/website/docs/img/flow-compiled-example.png" target="_blank" title="Click to view full size">
  <img src="/website/docs/img/flow-compiled-example.png" alt="Compiled flow graph: text analysis pipeline with language-based branching" style="max-width: 80%; cursor: zoom-in;"/>
</a>
</p>
<p align="center"><em>Green = actor handlers (your code).<br/>Orange = auto-generated routers.<br/>Blue = entrypoint/exitpoint.</em></p>

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
| `if/elif/else` | Conditional route rewrite |
| `while` / `while True` with `break` | Loop-back edges with exit conditions |
| `payload["results"] = [x for x in payload["items"]]` | Fan-out with automatic fan-in |
| `asyncio.gather(a, b)` | Fan-out with automatic fan-in (for asyncio flows) |
| `try/except` | Error routing to recovery actors |
| `with asyncio.timeout()` | SLA-bounded execution |

## Flows vs standalone actors

Flows compile to standard actors, but the compiler enforces **1:1 payload
mapping** — each actor call takes one payload and returns one payload. This
keeps the compiled graph predictable and debuggable.

For advanced patterns that break this contract, use standalone generator actors
directly:

| Pattern | Flow | Standalone actor |
|---------|------|-----------------|
| Sequential, branching, loops | ✅ | ✅ |
| Early return | ✅ | ✅ |
| Fan-out / fan-in | ✅ | ✅ |
| Fire-and-forget fan-out (multiple yields) | use standalone | ✅ |
| Streaming events (FLY) | use standalone | ✅ |

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
