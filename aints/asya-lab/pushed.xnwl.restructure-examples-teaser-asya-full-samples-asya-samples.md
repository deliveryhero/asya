---
title: "Restructure examples: teaser in asya, full samples in asya-samples"
priority: 2 # medium
tags:
  - pr:413
  - pr:asya-samples/1
---


## Context

`examples/` has grown into a compiler test suite (~89 flows, 100+ compiled dirs).
It's overwhelming for users exploring Asya. The goal is to split into:

- **asya/examples/** — curated teaser showing what Asya artifacts look like (referenced from docs)
- **asya-samples** (github.com/asyacore/asya-samples) — full working monorepo with all patterns, tested on GKE

The `demo-kubecon` example has already been deleted on branch `delete-demo`.

## Design

### Part 1: asya/examples/ (teaser)

Keep **one representative flow per pattern family** (~14 files) with:
- PNG graph visualization next to each .py file (requires CLI patch: `asya compile --png-only`)
- One fully compiled flow (e.g. `01_sequential`) showing manifests/routers/graphs
- A few AsyncActor YAML specs (simple, gpu, pipeline)
- A few actor handler examples (agentic patterns)
- Shared `.asya/` config (demo-repo style)
- README with clear explanations of what each file demonstrates, linking to asya-samples

**CLI prerequisite:** compiler currently cannot generate only PNG files.
Need to patch `asya flow compile` to support a `--png-only` or `--artifacts-only` flag.
The examples Makefile/pre-commit should use this flag for the teaser flows.
Track as separate aint (dependency).

#### Flows to keep (numbered for navigation order):

| # | Pattern | File | Why |
|---|---|---|---|
| 00 | minimal | `00_minimal.py` | simplest possible flow |
| 01 | sequential | `01_sequential.py` | multi-step pipeline (**fully compiled**) |
| 02 | if/else | `02_if_else.py` | basic branching |
| 03 | while loop | `03_while_loop.py` | basic iteration |
| 04 | fanout (parallel) | `04_fanout.py` | heterogeneous parallel dispatch |
| 05 | try/except | `05_try_except.py` | error handling |
| 06 | flow composition | `06_composition.py` | subflow inlining |
| 07 | mutations | `07_mutations.py` | payload mutations |
| 08 | decorators | `08_decorators.py` | @actor/@inline classification |
| 09 | typed signatures | `09_typed_pipeline.py` | TypedDict schema clarity |
| 10 | async sequential | `10_async_sequential.py` | async/await pipeline |
| 11 | resiliency | `11_resiliency.py` | retry with tenacity + timeouts |
| 12 | react loop | `12_react_loop.py` | LLM agent with tools |
| 13 | human-in-the-loop | `13_human_in_the_loop.py` | pause/resume pattern |

Ordering: basic syntax first (00-07), then compiler sugar (08-10), then advanced (11-13).

#### Files to keep:
- `_asya_utils.py` — shared no-op decorators
- `.asya/` — config, compiler rules, templates
- `asyas/simple-actor.yaml`, `asyas/gpu-actor.yaml`, `asyas/pipeline-*.yaml` — CRD reference
- `actors/agentic/` — all 3 handler examples

#### Files to remove:
- All other flows (60+ files) — move to asya-samples
- All compiled output except sequential — remove (regenerated in asya-samples)
- `examples/flows/agentic/` — all 18 files move to asya-samples
- `requirements.txt` — not needed for stubs

### Part 2: asya-samples/ (full monorepo)

Real-world monorepo structure with central `.asya/` and per-category configs.

Actors and flows are separated: `actors/` for handler implementations, `flows/` for
flow definitions. Flow files prefixed `flow_`, actor files prefixed `actor_` where
naming could be ambiguous. Each category group shares a Dockerfile + skaffold.yaml
(one image per group, not per file).

```
asya-samples/
  .asya/                              # org-wide config (registry, templates, contexts)
    config.yaml                       #   registry, default namespace, GKE + Kind contexts
    config.compiler.rules.yaml        #   tenacity, asyncio.timeout extraction rules
    templates/                        #   actor.yaml, router.yaml, configmap, kustomization
    flows/                            # all compiled output (code, manifests, artifacts)
      text-improver/
      control-flow--if-elif-else/
      agentic--multi-agent-debate/
      ...
  src/
    control-flow/                     # --- category: control flow patterns ---
      __init__.py
      Dockerfile
      skaffold.yaml                   #   artifact: asya-samples-control-flow
      flows/
        flow_if_elif_else.py
        flow_while_with_break.py
        flow_fanout_comprehension.py
        flow_nested_if.py
        flow_while_nested.py
        ...
      actors/
        __init__.py
        handler_a.py                  #   stub actors shared across control-flow flows
        handler_b.py
        ...
    compiler-sugar/                   # --- category: compiler sugar ---
      __init__.py
      Dockerfile
      skaffold.yaml                   #   artifact: asya-samples-compiler-sugar
      flows/
        flow_decorator_callsite.py
        flow_typed_pydantic.py
        flow_adapter_pattern.py
        flow_inline_overrides.py
        ...
      actors/
        __init__.py
        ...
    agentic/                          # --- category: agentic patterns ---
      __init__.py
      Dockerfile
      skaffold.yaml                   #   artifact: asya-samples-agentic
      flows/
        flow_evaluator_optimizer.py
        flow_multi_agent_debate.py
        flow_human_in_the_loop.py
        flow_react_tool_loop.py
        flow_orchestrator_workers.py
        ...
      actors/
        __init__.py
        actor_proposal_generator.py
        actor_approval_gate.py
        ...
    resiliency/                       # --- category: resiliency patterns ---
      __init__.py
      Dockerfile
      skaffold.yaml                   #   artifact: asya-samples-resiliency
      flows/
        flow_resiliency_combined.py
        flow_error_routing.py
        flow_retry_loop.py
        ...
      actors/
        __init__.py
        ...
    text-improver/                    # --- anchor example (from demo-kubecon2026) ---
      __init__.py
      Dockerfile
      skaffold.yaml                   #   artifact: asya-samples-text-improver
      flows/
        flow_text_improver.py
      actors/
        __init__.py
        research.py
        generate.py
        evaluate.py
        polish.py
  requirements.txt                    # shared deps (litellm, tenacity)
  pyproject.toml
  README.md
```

Key properties:
- All Python code in `src/` as proper packages
- All generated code/files in `.asya/flows/`
- Central `.asya/config.yaml` with registry, contexts (dev GKE + local Kind)
- **Separate `actors/` and `flows/` dirs** within each category
- **One Dockerfile + skaffold.yaml per category** (monorepo pattern, one image per group)
- `text-improver` from demo-kubecon2026 as the anchor real-world example
- README explains categories and how to compile/deploy
- Stub actors (control-flow, compiler-sugar) use no-op handlers; real actors
  (text-improver, some agentic) have actual LLM calls via litellm

### Part 3: PRs

1. **asya repo PR** (branch `delete-demo`): trim examples/, add README, update docs links
2. **asya-samples PR**: populate the monorepo with all patterns + text-improver

## Implementation steps

1. Trim `asya/examples/flows/` — delete non-representative flows and compiled output
2. Trim `asya/examples/asyas/` — keep simple, gpu, pipeline-* only
3. Generate PNGs for kept flows, keep one fully compiled
4. Write `examples/README.md` with clear structure explanation
5. Populate `asya-samples/` with categories, config, and all moved flows
6. Port `asya-demo-kubecon2026` content into `asya-samples/src/text-improver/`
7. Create PRs for both repos
