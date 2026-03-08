# RFC: Asya Lab -- Python SDK, CLI, and Jupyter Magics

**Status**: Proposed (revised 2026-03-08)
**Date**: 2026-02-27 (original), 2026-03-08 (revised)
**Epic**: 1jux.asya-lab
**Depends on**: 1jow (client UX design)
**Supersedes**: 1jpc (client-cli)

---

## 1. Summary

`asya-lab` is the unified Python package (PyPI) that consolidates the SDK, CLI,
Jupyter magics, and local HTTP server into a single coherent tool. It replaces
the existing `asya-cli` package. The core principle: the SDK is the single
source of truth for all logic; every other surface is a thin wrapper.

---

## 2. Package Naming

`asya` is taken on PyPI. `asya-lab` was chosen: DS-native, signals
experimentation and tooling, short and memorable.

Rejected: `asya-sdk` (generic), `asya-client` (generic), `asya-stage`
(less intuitive), `asya-plants`/`asya-stooge` (confusing).

---

## 3. Package Structure

### 3.1 Extras

```bash
pip install asya-lab              # core: compiler, project config, MCP/A2A client
pip install asya-lab[ui]          # + FastAPI server + bundled React SPA
pip install asya-lab[jupyter]     # + Jupyter magics, rich output, inline visualization
pip install asya-lab[deploy]      # + kubectl/helm wrappers for deployment
pip install asya-lab[all]         # everything
```

Core has minimal dependencies (requests, pyyaml, tqdm, graphviz, omegaconf).

### 3.2 Module Layout

```
asya_lab/
├── __init__.py
├── compile/              # Layered compiler
│   ├── frontends/        # Flow DSL (+ future: simplified YAML, CRD)
│   ├── ir.py             # Canonical actor spec IR
│   └── rules.py          # treat-as rules engine
├── project/              # .asya/ config, actor discovery
│   ├── config.py         # config.yaml loading + walk-up merge
│   ├── discovery.py      # Actor discovery from local + pip packages
│   └── env.py            # .env file loading/merging via load_dotenv
├── mcp/                  # Gateway client (refactored from existing CLI)
├── testing/              # VFS fixtures, state mocks (pytest fixtures)
├── server/               # [ui] FastAPI/Starlette local server
│   └── static/           # [ui] Bundled @asya/ui React SPA
├── jupyter/              # [jupyter] Magic functions
├── deploy/               # [deploy] K8s/Docker interaction
└── cli/                  # CLI entry point (thin wrapper)
```

### 3.3 Entry Points

```toml
[project.scripts]
asya = "asya_lab.cli:main"
```

The CLI binary is still `asya`. Only the package name on PyPI is `asya-lab`.

---

## 4. SDK API

```python
import asya_lab as asya

# --- Compile ---
asya.flow.compile("my_flows/order_processing.py")
asya.compile_all()

# --- Deploy ---
asya.flow.deploy("order-processing", context="k8s-stg")
asya.actor.deploy("text-analyzer", context="k8s-stg")

# --- Interact ---
result = asya.flow.call("analyze", {"text": "hello"}, protocol="mcp")
asya.flow.stream(task_id)

# --- Observe ---
asya.flow.status("order-processing")
asya.actor.logs("text-analyzer")

# --- Messages (low-level) ---
asya.msg.send("text-analyzer", {"text": "hello"})
asya.msg.trace(message_id)

# --- Project ---
asya.context.use("k8s-stg")
config = asya.project.load()
```

Each namespace is a module with public functions. No singleton state -- context
is passed explicitly or loaded from `.asya/config.yaml` / `ASYA_CONTEXT`.

---

## 5. CLI Commands

Commands are organized by domain abstractions: flow, actor, msg.

### 5.1 Flow Operations

```bash
asya flow compile <flow.py>          # compile flow -> routers + manifests
asya flow list                       # list all flows
asya flow expose <flow>              # register with gateway
asya flow call <flow> '{params}'     # call via gateway
asya flow stream <id>                # stream results
asya flow deploy <flow>              # deploy all actors in flow
asya flow undeploy <flow>            # undeploy all
asya flow status <flow>              # aggregated status
asya flow logs <flow>                # aggregated logs (colored actor-name prefix)
asya flow build <flow>               # build all images for flow
```

### 5.2 Actor Operations

```bash
asya actor list                      # list actors
asya actor deploy <actor>            # deploy single actor
asya actor undeploy <actor>          # undeploy
asya actor status <actor>            # replicas, queue depth
asya actor logs <actor>              # stream logs
asya actor build <actor>             # build actor image
asya actor template <actor>          # generate manifest from config
# asya actor lock <actor>              # lock actor image (not now - after v0)
```

### 5.3 Message Operations

```bash
asya msg send <actor-or-flow> '{}'   # send message to queue
asya msg trace <message-id>          # distributed trace
asya msg replay <message-id>         # replay failed message
asya msg inspect <actor>             # peek at queue/DLQ
asya msg drain <actor>               # drain DLQ
```

### 5.4 Project / Infrastructure

```bash
asya init                            # scaffold .asya/ project directory
asya serve                           # start local HTTP/WS server for UI
asya context list                    # list contexts
asya context use <name>              # switch context
# asya <actor/flow> promote                 # promote staging image to prod PR -> UNDEFINED, needs more design
```

### 5.5 Command Data Sources

No CLI command uses the gateway's internal `/mesh/*` routes -- those are
reserved for sidecar-to-gateway communication.

| Command | Backend | Protocol / API |
|---------|---------|---------------|
| `asya flow call <flow>` | Gateway | MCP `tools/call` or A2A `message/send` |
| `asya flow stream <id>` | Gateway | MCP streamable HTTP or A2A subscribe |
| `asya flow list` | Gateway or K8s | MCP `tools/list` / kubectl |
| `asya flow status <flow>` | K8s API | `kubectl get asya -l asya.sh/flow=<flow>` |
| `asya flow logs <flow>` | K8s API | `kubectl logs -l asya.sh/flow=<flow>` |
| `asya flow deploy/undeploy` | K8s API | `kubectl apply/delete` |
| `asya actor build` | Build tool | Opaque shell command from config.yaml |
| `asya msg send <target>` | MQ | Direct queue publish (SQS/RabbitMQ API) |
| `asya msg trace <id>` | Observability | OpenTelemetry trace query |

### 5.6 Protocol Handling

`asya flow call` and `asya flow expose` accept a `--protocol=mcp|a2a` flag.
Default is configurable. DS should not need to care about MCP vs A2A.

### 5.7 Log Display

`asya flow logs <flow>` aggregates logs from all actors in the flow, prefixed
with a colored actor name (like `docker compose logs`).

### 5.8 Deploy/Undeploy Semantics

Behavior depends on active context type:

| Context type | `deploy` | `undeploy` |
|---|---|---|
| `kubernetes` | `kubectl apply` manifests | `kubectl delete` manifests |
| `docker-compose` | `docker compose up -d` | `docker compose down` |

K8s safety rule: `asya flow deploy` checks for existing deployment. If a
different version exists, errors and asks to undeploy first. Identical version
exits 0 (idempotent).

---

## 6. Context System

All commands respect context, resolved in this order (highest priority first):

1. `--context` flag on the command
2. `ASYA_CONTEXT` environment variable
3. Default context in config

---

## 7. Project Configuration (`.asya/config.yaml`)

The project configuration lives in `.asya/config.yaml`. The `.asya/` directory
marks the project root (like `.git/`). Created by `asya init`.

### 7.1 Top-Level Structure

```yaml
project_root: "."
image_registry: ghcr.io/org
router_image: python:3.13-slim

asya:
  build:
    - module: e_commerce
      path: "${project_root}/src/e-commerce-package"
      image: "${image_registry}/e-commerce:${arg:tag}"
      command:
        local: "docker build -t ${..image} ."
        remote: "docker build -t ${..image} . && docker push ${..image}"
  
  compile:
    # compiler rules (treat-as, extraction config)
  
  template:
    output: ".asya/manifests"
    mode: manifests          # manifests | helm | kustomize
    body:
      apiVersion: asya.dev/v1alpha1
      kind: AsyncActor
      metadata:
        name: "${actor:name}"
      spec:
        image: "${actor:image}"
        handler: "${actor:handler}"
        transport: sqs
        env: "${actor:env}"
```

### 7.2 Key Design Decisions

- **Build context follows Python packages, not actors**: Multiple actors can
  share one image if their handlers come from the same package.
- **Build commands are opaque**: Asya is a thin command runner, not a build
  system. `command.local` and `command.remote` are shell strings with variable
  substitution. Any build tool works.
- **Walk-up recursive merge**: Nested `.asya/` directories support monorepos.
  Configs merge root-first (dicts deep-merge, lists concatenate).
- **OmegaConf interpolation**: `${key}` for top-level config values, `${arg:*}` for
  CLI args, `${actor:*}` for compiler-inferred values, `${env:*}` for env vars.
- **Template modes**: `manifests` (raw AsyncActor XRs), `helm` (values.yaml),
  `kustomize` (patches). No custom plugins needed.

> **Full design**: `research-compiler-resolution.md` (sections 2-3: `.asya/`
> directory, config schema, walk-up merge, variable interpolation, template
> modes, `asya init`).

---

## 8. Five Stages

The lifecycle is five distinct stages:

| Stage | CLI | Input | Output |
|-------|-----|-------|--------|
| **Compile** | `asya flow compile` | flow.py + config.yaml | routers.py + metadata |
| **Template** | `asya [flow\|actor] template` | metadata + template config | deployment files |
| **Build** | `asya [flow\|actor] build` | source + build commands | OCI image |
| **Deploy** | `asya [flow\|actor] deploy` | manifests | running pods |
| **Runtime** | (automatic) | envelope | handler response |

Compile invokes template by default (`--no-template` to skip). Build and deploy
use `--local`/`--remote` flags for execution context.

> **Full design**: `research-compiler-resolution.md` (section 4: five stages,
> Python environment detection, verbose output, resolution chain).

---

## 9. Flow Compiler

### 9.1 Compiler Rules (`treat-as` System)

Every symbol the compiler encounters is classified into one of five actions:

| Value | Meaning | Creates boundary? |
|-------|---------|-------------------|
| `unfold` | Expand function body into current flow | No |
| `inline` | Run code inside router verbatim | No |
| `actor` | Message boundary, separate deployment | Yes |
| `flow` | Sub-flow, compile recursively | Yes |
| `config` | Strip and extract infrastructure metadata | No |

Rules are declared in `compile.rules` in config.yaml. Most-specific pattern
wins. Inline comments (`# asya: <action>`) have highest priority.

### 9.2 Implemented Constructs

These are implemented (PRs #278, #280, #281):

- **Inline comment overrides** [pyn3]: `# asya: actor`, `# asya: inline`, etc.
- **Decorator detection** [srn2]: Decorators on function definitions matched
  against rules independently.
- **Decorator stripping** [n67c]: `treat-as: config` strips decorators and
  extracts args into env vars.
- **Call-site application** [xx8t]: `p = actor(handler)(p)` pattern -- outer
  function looked up in rules, inner function is the classified symbol.
- **Context managers** [2t1q]: `with`/`async with` matched by rules.
  `treat-as: config` strips and extracts; `treat-as: inline` keeps in router.

### 9.3 Config Extraction

When `treat-as: config`, the compiler uses `inspect.signature` at compile time
to bind decorator/context-manager arguments to Asya resiliency env vars
(`ASYA_RESILIENCY_RETRY_MAX_ATTEMPTS`, `ASYA_RESILIENCY_ACTOR_TIMEOUT`, etc.).
Works with tenacity, stamina, asyncio.timeout, and any library with inspectable
signatures.

### 9.4 Defaults

| Situation | Default | Override |
|-----------|---------|----------|
| Same-package function | `unfold` | Inline comment or rule |
| External function | `inline` | Specific rule |
| Decorator, no rule | Keep at runtime | `treat-as: config` rule |

> **Full design**: `research-compiler-knowledge-base.md` (rules engine, pattern
> matching, extraction design, tenacity signatures).
> **Implementation tasks**: pushed [pyn3], [srn2], [n67c], [xx8t], [2t1q];
> backlog [1fmi] (rules engine with default rule set).

---

## 10. Flow Deployment (Label-Based)

Flow deployment uses labels + CLI tooling (no separate AsyncFlow CRD).

### 10.1 Label Convention

| Label | Purpose | Values |
|---|---|---|
| `asya.sh/flow` | Flow membership (1:M) | Flow name |
| `asya.sh/flow-role` | Role within flow | `entrypoint`, `exitpoint`, `router`, `processor` |

One actor belongs to at most one flow. If the same handler is needed in multiple
flows, the actor is cloned.

### 10.2 What `asya flow deploy` Does

1. Creates AsyncActor manifests for routers (with flow labels)
2. Updates processor actor manifests (adds flow label)
3. Marks entrypoint/exitpoint actors
4. Creates ConfigMap with router code
5. Supports `--output-dir` for GitOps

### 10.3 Router Actors

Routers are lightweight (pure Python routing logic). They use the
`router_image` base image with code injected via ConfigMap. No custom build
needed. Platform engineers define a `flow-router` flavor for minimal resources.

---

## 11. Image Building

### 11.1 Three Build Paths

| Path | CUDA? | Lock file (v1)? | Best for |
|------|-------|-----------------|----------|
| **Cog** | Auto-resolved | No | GPU/ML actors, DS experimentation |
| **Dockerfile** | Manual | No | Full control, existing CI pipelines |
| **apko** (Wolfi) | Not yet | Yes (`actor-image.lock`) | Lockable, reproducible, non-GPU |

Strategy is always explicit in config.yaml (no auto-detection).

### 11.2 CUDA Auto-Resolution

Asya reuses Cog's compatibility matrices (Apache 2.0) for PyTorch/TensorFlow
CUDA version resolution -- without depending on Cog as a build tool.

### 11.3 Cog as GPU Build Path

Cog is a **supported build path** for GPU/ML actors. DS writes `cog.yaml`,
Asya runs `cog build` as an opaque command. Cog auto-resolves CUDA versions.
Known trade-offs: dead coglet server (no runtime impact), devel-only CUDA
images (larger), Docker dependency (local builds only).

> **Full design**: `research-no-dockerfile.md` (tool analysis, comparison
> matrix, golden paths).
> **ADR**: `adr.no-cog.md` (revised: Cog as supported path).

---

## 12. Build and Deploy Workflows

### 12.1 Two User Flows

**DS experimentation (staging)**: Fast, imperative, no git commit required.
```
asya actor build my-actor --local --arg tag=v1
asya actor deploy my-actor --context=k8s-stg
```

**Production (GitOps)**: Declarative, reviewed, git-driven.
```
asya promote my-actor --context=k8s-prod
# -> verifies actor-image.lock, creates PR with source + lock + manifest
```

### 12.2 Promotion (`asya promote`)

Three promotion strategies:

| Strategy | What's in PR | Rebuild? | Same as staging? |
|---|---|---|---|
| **A: Lock only** | Lock + manifest | No | Yes |
| **B: Source only** | Source + config | Yes (CI) | No |
| **C: Source+Lock** (default) | Source + lock + manifest | No (verify only) | Yes |

`actor-image.lock` maps build inputs (handler code, requirements, build config)
to a pinned image digest. `asya promote` enforces consistency.

### 12.3 Build Execution

Build strategy (WHAT) and execution (WHERE) are independent:

| | Local | Shipwright (on-cluster) | CI/CD |
|---|---|---|---|
| apko | `apko build` | apko strategy | `apko build` |
| Buildpacks | `pack build` | buildpacks strategy | `pack build` |
| Dockerfile | `docker build` | kaniko strategy | `docker build` |

> **Full design**: `research-seamless-build.md` (build execution, promotion
> strategies, lock file model, Shipwright integration).

---

## 13. MCP Client Refactoring

The existing MCP client in `src/asya-cli/asya_cli/mcp/` moves into
`asya_lab/mcp/`:

```python
from asya_lab.mcp import MCPClient

client = MCPClient(gateway_url="http://localhost:8080")
tools = client.list_tools()
result = client.call_tool("analyze", {"text": "hello"})
for event in client.stream(result.task_id):
    print(event)
```

---

## 14. `asya serve` (UI Extra)

The `[ui]` extra installs FastAPI and bundles the `@asya/ui` React SPA as
static files. `asya serve` starts the local HTTP/WS server consumed by VSCode
extension, standalone web, and asya-lens Docker image.

See epic 1juv for the full `asya serve` API specification.

---

## 15. Jupyter Magics (Jupyter Extra)

### 15.1 How Magics Work

Jupyter magic functions (`%`/`%%`) are Python extensions with notebook context
access. The magic can inspect locally developed flows, auto-detect project
config, and render rich interactive output.

### 15.2 Basic Usage

```python
%load_ext asya_lab

%asya flow compile order_processing
%asya flow status order-processing
%asya flow call analyze '{"text": "hello world"}'
%asya flow stream <task-id>
```

### 15.3 Interactive Visualization

Flow compilation renders an interactive graph inline. Nodes are actors/routers,
edges are message routes. Clicking a node reveals configuration, live logs,
and queue depth.

---

## 16. Testing Fixtures (`asya_lab.testing`)

```python
from asya_lab.testing import vfs_fixture

def test_router_modifies_route(vfs_fixture):
    vfs_fixture.set_route(prev=[], curr="router-1", next=["actor-a", "actor-b"])
    from my_routers import start_router
    result = start_router({"type": "express"})
    assert vfs_fixture.get_route_next() == ["express-handler", "actor-b"]
```

---

## 17. Migration from asya-cli

### 17.1 Migration Path

1. Create `src/asya-lab/` with new package structure
2. Move MCP client to `asya_lab/mcp/`
3. Move flow compiler to `asya_lab/compile/frontends/flow_dsl/`; IR to
   `asya_lab/compile/ir.py`
4. Add new modules incrementally (project, deploy, testing, server, jupyter)
5. Deprecate `asya-cli` package
6. CLI entry point (`asya`) stays the same

### 17.2 Backward Compatibility

- `asya mcp *` commands continue to work
- `asya flow compile` and `asya flow validate` continue to work
- Only the package name changes (`asya-cli` -> `asya-lab`)

---

## 18. Phasing

### Phase 1: Core SDK + CLI restructure
- Package creation, migration from asya-cli
- SDK extraction (compiler, MCP client)
- `.asya/config.yaml` schema, walk-up merge, `asya init`
- Template stage (manifests mode)
- Flow and actor commands (list, status, logs)

### Phase 2: Build + deploy + testing
- `asya [flow|actor] build` (opaque commands, `--local`/`--remote`)
- `asya [flow|actor] deploy/undeploy` for K8s and Docker Compose
- `actor-image.lock` and `asya promote`
- `asya_lab.testing` pytest fixtures

### Phase 3: Compiler rules + message operations + Jupyter
- `compile.rules` engine with default rule set [1fmi]
- Config extraction (`treat-as: config`)
- `asya msg send/trace/replay/inspect/drain`
- Jupyter magics, interactive flow visualization

### Phase 4: Server + advanced features
- `asya serve` local HTTP/WS server
- Template modes: helm, kustomize
- Protocol-agnostic `asya flow call` (MCP + A2A)

---

## 19. Related Epics

| Epic | Relationship |
|---|---|
| 1jow (Client UX Design) | Parent design |
| 1jpc (Client CLI) | Superseded by this RFC |
| 1juv (Asya UI) | `@asya/ui` bundle goes into `[ui]` extra |
| 1juy (Asya Lens) | Docker image that packages `asya-lab[ui,deploy]` |
| 1is3 (GitOps Flow Design) | Informs deploy/undeploy semantics |
| 1g2t (Gateway Dynamic Tool Exposure) | Powers `asya flow expose` |
| 1iu4 (Local Testing Workflow) | Informs Docker Compose context |

---

## 20. Research Documents

Detailed designs that inform this RFC:

| Document | Covers |
|---|---|
| `research-compiler-resolution.md` | `.asya/` directory, config.yaml schema, walk-up merge, OmegaConf interpolation, five stages, template modes, Python resolution |
| `research-compiler-knowledge-base.md` | Compiler rules engine, `treat-as` values, pattern matching, config extraction, tenacity/stamina signatures |
| `research-no-dockerfile.md` | Build strategies (apko, buildpacks, Cog, Wolfi/distroless), comparison matrix, golden paths |
| `research-seamless-build.md` | Build execution (local, Shipwright, CI), promotion strategies, `actor-image.lock`, two user flows |
| `artem-research-compiler-resolution.md` | Four stages overview, compile-time resolution chain, `asya.yaml` role |
| `adr.no-cog.md` | Decision to not use Cog as build strategy |
| `adr.compiler-template-not-helm.md` | Template uses OmegaConf resolvers, not Helm |

---

## 21. Open Questions

1. **Click vs argparse**: Current CLI uses argparse. Should the new CLI use
   Click?

2. **Jupyter widget framework**: ipywidgets vs JupyterLab extensions vs static
   SVG.

3. **Docker Compose generation**: Should `asya compile --context=docker`
   generate a full `docker-compose.yaml` or a partial overlay?

4. **Non-Python actors**: The `module:` field is Python-specific. Go actors,
   shell scripts, or pre-built images need a different matching strategy.

5. **`${arg:tag}` lifecycle per template mode**: Should `${arg:*}` in template
   body always resolve at template time, or be mode-dependent?

6. **Lock file vs opaque builds**: Opaque build commands limit `actor-image.lock`
   to tracking final image digest, not input reproducibility. Acceptable for v1;
   structured `build.intent:` can be added later without schema break.

See also open questions in `research-compiler-resolution.md` (section 8) and
`research-seamless-build.md` (section 8).
