---
title: "Restructure examples: teaser in asya, full samples in asya-samples"
priority: 2 # medium
---

## Context

`examples/` has grown into a compiler test suite (~89 flows, 100+ compiled dirs).
It's overwhelming for users exploring Asya. The goal is to split into:

- **asya/examples/** — curated teaser showing what Asya artifacts look like (referenced from docs)
- **asya-samples** (github.com/asyacore/asya-samples) — full working monorepo with all patterns, tested on GKE

The `demo-kubecon` example has already been deleted on branch `delete-demo`.

## Design

### Part 1: asya/examples/ (teaser)

Keep **one representative flow per pattern family** (~15-20 files) with:
- PNG graph visualization next to each .py file
- One fully compiled flow (e.g. `sequential`) showing manifests/routers/graphs
- A few AsyncActor YAML specs (simple, gpu, pipeline)
- A few actor handler examples (agentic patterns)
- Shared `.asya/` config (demo-repo style)
- README with clear explanations of what each file demonstrates, linking to asya-samples

#### Flows to keep (one per pattern):

| Pattern | File | Why |
|---|---|---|
| minimal | `minimal.py` | simplest possible flow |
| sequential | `sequential.py` | multi-step pipeline (fully compiled) |
| if/else | `if_else_simple.py` | basic branching |
| while loop | `while_simple.py` | basic iteration |
| fanout (parallel) | `fanout_literal.py` | heterogeneous parallel dispatch |
| try/except | `try_except_simple.py` | error handling |
| flow composition | `flow_composition_simple.py` | subflow inlining |
| react loop | `react_loop.py` | LLM agent with tools |
| async sequential | `async_sequential.py` | async/await pipeline |
| decorators | `decorator_definitions.py` | @actor/@inline classification |
| typed signatures | `typed_dict_pipeline.py` | TypedDict schema clarity |
| resiliency | `resiliency_retry_patterns.py` | retry with tenacity + timeouts |
| mutations | `mutations_with_handler.py` | payload mutations |
| human-in-the-loop | `agentic/human_in_the_loop.py` | pause/resume pattern |

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

Real-world monorepo structure with central `.asya/` and per-category configs:

```
asya-samples/
  .asya/                          # org-wide config (registry, templates, contexts)
    config.yaml
    config.compiler.rules.yaml
    templates/
    flows/                        # all compiled output lands here
      text-improver/
      sequential-pipeline/
      ...
  src/
    control-flow/                 # if/else, while, fanout, composition, mutations
      __init__.py
      if_elif_else.py
      while_with_break.py
      fanout_comprehension.py
      ...
    compiler-sugar/               # adapters, decorators, typed sigs, inline overrides
      __init__.py
      decorator_callsite.py
      typed_pydantic_pipeline.py
      ...
    agentic/                      # react, streaming, hitl, multi-agent, orchestrator
      __init__.py
      evaluator_optimizer.py
      multi_agent_debate.py
      ...
    resiliency/                   # retry, error routing, failover, timeouts
      __init__.py
      resiliency_combined.py
      ...
    text-improver/                # from demo-kubecon2026 (anchor example)
      __init__.py
      flow_text_improver.py
      actors/
        research.py
        generate.py
        evaluate.py
        polish.py
  Dockerfile
  skaffold.yaml
  requirements.txt
  pyproject.toml
  README.md
```

Key properties:
- All Python code in `src/` as proper packages
- All generated code/files in `.asya/flows/`
- Central `.asya/config.yaml` with registry, contexts (dev GKE + local Kind)
- `text-improver` from demo-kubecon2026 as the anchor real-world example
- Each category is a Python package under `src/`
- README explains categories and how to compile/deploy

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
