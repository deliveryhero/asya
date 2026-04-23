# End-to-End Examples (Monorepo)

Full working examples for [Asya](https://github.com/asyacore/asya) — the
Actor Mesh framework for running AI workloads on Kubernetes.

## What is this?

Asya compiles Python control flow (if/else, while, fan-out, try/except) into a
mesh of actors connected by message queues. You write a flow as a regular Python
function, and the compiler generates Kubernetes manifests, router actors, and
adapter code.

This directory is a **monorepo of working examples** organized by pattern
category. Each category has its own `Dockerfile` and `skaffold.yaml` — one
container image per group, just like a real multi-team setup.

For a quick overview of what Asya flows look like, see the
[teaser examples](../flows/) in `examples/flows/`. This directory has the full,
deployment-ready versions.

## Structure

```
.asya/                          # Central config (shared across all categories)
  config.yaml                   #   registry, templates, compiler paths
  config.compiler.rules.yaml    #   decorator/context-manager extraction rules
  templates/                    #   actor.yaml, router.yaml, configmap, kustomization
  flows/                        #   All compiled output lands here

src/
  control-flow/                 # if/elif/else, while, fan-out, composition, mutations
  compiler-sugar/               # adapters, decorators, typed signatures, bare scripts
  agentic/                      # ReAct, multi-agent debate, human-in-the-loop
  resiliency/                   # retry, error routing, try/except, timeouts
  text-improver/                # end-to-end example with real LLM calls
```

Each category contains:

```
src/<category>/
  flows/flow_*.py     # Flow definitions (compiled by `asya flow compile`)
  actors/*.py         # Actor handler implementations (deployed as containers)
  Dockerfile          # Container image for this category
  skaffold.yaml       # Build config (artifact name, context)
```

## Categories

### control-flow/ (29 flows)

Core compiler patterns showing every control-flow construct the compiler supports:

- **Branching**: if/elif/else, nested conditionals, empty branches, early return
- **Loops**: while, break, continue, nested loops, mutations in loop body
- **Fan-out**: list literals (heterogeneous), comprehensions (homogeneous), `asyncio.gather`
- **Composition**: subflow inlining, nested composition
- **Mutations**: payload mutations before/after handlers, in branches, in loops

### compiler-sugar/ (13 flows)

Advanced compiler features beyond basic control flow:

- **Decorators**: `@tenacity.retry` extraction, `@actor`/`@inline` classification, call-site wrappers
- **Typed signatures**: TypedDict, Dataclass, Pydantic model pipelines
- **Inline overrides**: `# asya: actor` / `# asya: inline` comment directives
- **Adapters**: automatic wrapper generation for non-standard function signatures
- **Bare scripts**: flows without `@flow` decorator (using `# asya: flow` comment)

### agentic/ (19 flows)

Agentic AI patterns that map to established frameworks (ADK, LangGraph, Mastra):

- **ReAct loop**: LLM + tool calls in a while-true loop
- **Evaluator-optimizer**: generate-evaluate-refine cycle with scoring
- **Multi-agent debate**: multiple LLM agents argue to consensus
- **Human-in-the-loop**: pause for approval, revise on rejection
- **Orchestrator-workers**: coordinator dispatches to specialized agents
- **RAG pipeline**: retrieve-augment-generate with context injection
- **Voting ensemble**: multiple models vote on the answer
- **Hierarchical delegation**: manager delegates subtasks to specialists

### resiliency/ (13 flows)

Error handling and fault tolerance patterns:

- **try/except**: single handler, multiple handlers, catch-all, nested, finally, tuple types
- **Retry**: tenacity retry with backoff, retry loops, stamina retry
- **Error routing**: failover pipelines, conditional error recovery
- **Timeouts**: `asyncio.timeout` scopes (single and nested)

### text-improver/ (1 flow)

End-to-end example with **real LLM calls** via Gemini + LiteLLM. Ported from
[asya-demo-kubecon2026](https://github.com/atemate/asya-demo-kubecon2026).

Pipeline: research a topic, generate a draft, evaluate quality (0-100 score),
loop until quality threshold, then polish. Demonstrates while-loop with
conditional break, adapter generation, and multi-actor coordination.

## Quick Start

```bash
# Install the Asya CLI
pip install asya

# Compile a single flow
asya flow compile src/control-flow/flows/flow_if_elif_else.py

# Compile with flow graph visualization
asya flow compile src/text-improver/flows/flow_text_improver.py --plot

# Build a category's container image
cd src/text-improver && skaffold build

# Deploy compiled manifests to a cluster
asya k apply text-improver --context dev
```

## How it works

1. **Write a flow** as a Python function with `@flow` decorator
2. **`asya flow compile`** parses the AST, generates router actors (CPS transform),
   adapter wrappers, and Kubernetes manifests with kustomize layering
3. **`skaffold build`** builds the container image for your actors
4. **`asya k apply`** deploys everything to your cluster — actors auto-scale via KEDA

The compiler extracts retry/timeout config from Python decorators and context
managers (configured via `.asya/config.compiler.rules.yaml`) and writes them
into the actor manifests. Your handler code stays clean.

## Requirements

- Python 3.13+
- Asya CLI (`pip install asya` or `uv run --with asya-lab ...` from monorepo root)
- Docker + Skaffold (for building images)
- A Kubernetes cluster with Asya installed (for deployment)
