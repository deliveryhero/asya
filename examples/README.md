# Asya Examples

Curated examples showing what Asya artifacts look like. For full working examples
with real LLM calls, multiple categories, and GKE deployment, see
[end-to-end/monorepo/](end-to-end/monorepo/).

## Flow Examples (`flows/`)

The Asya compiler turns Python control flow into a mesh of actors connected by
message queues. These examples demonstrate each supported pattern — from a
single actor to agentic loops with human-in-the-loop.

Each `.py` file is a self-contained flow definition. Compile any of them with:

```bash
asya flow compile flows/01_sequential.py
```

| # | File | Pattern | What it shows |
|---|------|---------|---------------|
| 00 | `00_minimal.py` | Minimal | Single actor — simplest possible flow |
| 01 | `01_sequential.py` | Sequential | Multi-step pipeline (A -> B -> C) |
| 02 | `02_if_else.py` | Branching | Conditional routing based on payload |
| 03 | `03_while_loop.py` | Looping | Iterative processing with a counter |
| 04 | `04_fanout.py` | Fan-out | Parallel dispatch to multiple actors |
| 05 | `05_try_except.py` | Error handling | Route to error handler on exception |
| 06 | `06_composition.py` | Composition | Subflow inlined into outer flow |
| 07 | `07_mutations.py` | Mutations | Payload mutations grouped before handler |
| 08 | `08_decorators.py` | Decorators | `@actor` vs `@inline` classification |
| 09 | `09_typed_pipeline.py` | Typed signatures | TypedDict for self-documenting payloads |
| 10 | `10_async_sequential.py` | Async/await | Async pipeline with `await` calls |
| 11 | `11_resiliency.py` | Resiliency | Retry with `@tenacity` + `asyncio.timeout` |
| 12 | `12_react_loop.py` | ReAct loop | LLM agent with tool calls in a loop |
| 13 | `13_human_in_the_loop.py` | Human-in-the-loop | Pause for approval, revise on rejection |

## AsyncActor Manifests (`asyas/`)

Reference YAML specs for the `AsyncActor` CRD — the Kubernetes resource that
deploys an actor with its sidecar, scaling, and queue configuration.

| File | What it shows |
|------|---------------|
| `simple-actor.yaml` | Minimal actor with a message queue |
| `gpu-actor.yaml` | GPU-accelerated actor for AI inference |
| `pipeline-preprocess.yaml` | Multi-actor pipeline: preprocessing stage |
| `pipeline-inference.yaml` | Multi-actor pipeline: inference stage |
| `pipeline-postprocess.yaml` | Multi-actor pipeline: postprocessing stage |

Deploy:
```bash
kubectl apply -f asyas/simple-actor.yaml
```

## Actor Handlers (`actors/`)

Python handler functions that run inside actors. These show agentic patterns
that use the ABI yield protocol for dynamic routing, streaming, and pause/resume.

| File | Pattern |
|------|---------|
| `agentic/dynamic_routing.py` | Override routing at runtime via `yield "SET"` |
| `agentic/live_streaming.py` | Stream tokens to clients via `yield "FLY"` |
| `agentic/pause_for_human.py` | Pause envelope to S3 for human review |

## More Examples

For comprehensive, deployment-ready examples organized by pattern category:

- **[end-to-end/monorepo/](end-to-end/monorepo/)** — full monorepo with
  control-flow, compiler-sugar, agentic, and resiliency pattern categories.
  Includes real LLM actors, Dockerfiles, Skaffold configs, and GKE deployment.
