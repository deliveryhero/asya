# RFC: Client CLI, Python SDK, and Jupyter Magics

**Status**: Proposed
**Date**: 2026-02-26
**Epic**: 1jpc.client-cli
**Depends on**: 1jow.client-ux (client UX design)

---

## 1. Problem Statement

The current `asya-cli` package (in `src/asya-cli/`) provides basic MCP gateway
commands and flow compilation. However, it has several limitations:

- **No SDK**: CLI commands embed logic directly -- there is no importable Python
  API. Users cannot script Asya operations from Python code or notebooks.
- **Fragmented commands**: MCP and flow commands exist but there is no unified
  abstraction layer (flow, actor, message) that maps to how data scientists think.
- **No project model**: No `asya.yaml` config, no context system, no actor
  discovery. Each command operates in isolation.
- **No deploy/undeploy**: No commands for deploying actors or flows to K8s or
  Docker Compose targets.
- **No Jupyter integration**: Data scientists must leave their notebook environment
  to interact with Asya.

This RFC defines the unified `asya` Python package that consolidates the SDK, CLI,
and Jupyter magics into a single coherent tool.

---

## 2. Python SDK (`asya` package)

### 2.1 Package Structure

Single package with optional extras:

```
pip install asya              # core: compiler, project config, mcp/a2a client
pip install asya[ui]          # adds FastAPI server for VSCode/web UI
pip install asya[jupyter]     # adds Jupyter magics, rich output, inline visualization
pip install asya[deploy]      # adds kubectl/helm wrappers for deployment
pip install asya[all]         # everything
```

The core install has minimal dependencies (requests, pyyaml, tqdm, graphviz)
and covers the most common workflows: compiling flows, calling the gateway,
and managing project configuration.

### 2.2 Module Layout

```
asya/
├── compile/          # Layered compiler
│   ├── frontends/    # Simplified YAML, CRD, Flow DSL
│   ├── ir.py         # Canonical actor spec IR
│   └── backends/     # Not in compiler -- external adapters
├── project/          # Project config, actor discovery
│   ├── config.py     # asya.yaml loading
│   ├── discovery.py  # actor discovery
│   └── env.py        # .env file loading via load_dotenv
├── mcp/              # Gateway client (refactored from existing asya-cli)
├── testing/          # VFS fixtures, state mocks (pytest fixtures)
├── server/           # [ui] FastAPI/Starlette local server
├── jupyter/          # [jupyter] Magic functions
├── deploy/           # [deploy] K8s/Docker interaction
└── cli/              # CLI entry point (thin wrapper)
```

**Key principle**: The CLI is a thin wrapper. Every CLI command maps 1:1 to a
public SDK function. The CLI parses arguments, calls the SDK, and formats output.

### 2.3 SDK API

The SDK exposes a domain-oriented API organized by abstraction level:

```python
import asya

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

Each namespace (`asya.flow`, `asya.actor`, `asya.msg`, `asya.context`,
`asya.project`) is a module with public functions. No singleton state -- context
is passed explicitly or loaded from `asya.yaml` / `ASYA_CONTEXT` env var.

### 2.4 Compiler Refactoring

The existing flow compiler in `src/asya-cli/asya_cli/flow/` (parser, grouper,
codegen, dotgen, IR) moves into `asya/compile/frontends/flow_dsl/`. The IR
dataclasses (`IROperation`, `ActorCall`, `Condition`, etc.) move to
`asya/compile/ir.py` as the canonical intermediate representation shared
across all frontends.

New frontends (simplified YAML, CRD) can be added later without changing the
compiler core. Each frontend parses its input format into the same IR, then
the shared backend (codegen, dotgen) generates output.

### 2.5 MCP Client Refactoring

The existing MCP client code in `src/asya-cli/asya_cli/mcp/` (client.py,
commands.py, port_forward.py) moves into `asya/mcp/`. The client becomes a
standalone class that can be used programmatically:

```python
from asya.mcp import MCPClient

client = MCPClient(gateway_url="http://localhost:8080")
tools = client.list_tools()
result = client.call_tool("analyze", {"text": "hello"})
for event in client.stream(result.task_id):
    print(event)
```

The CLI command `asya mcp call` becomes a thin wrapper around `MCPClient.call_tool()`.

---

## 3. CLI (`asya` command)

### 3.1 Command Structure

Commands are organized by domain abstractions, not by implementation details.
Data scientists think in terms of flows (pipelines), actors (processing units),
and messages (data in transit).

#### Flow Operations (primary abstraction)

```bash
asya flow compile <flow.py>          # compile flow -> manifest
asya flow list                       # list all flows (exposed and internal)
asya flow expose <flow>              # register with gateway
asya flow call <flow> '{params}'     # call via gateway
asya flow stream <id>                # stream results
asya flow deploy <flow>              # deploy all actors in flow
asya flow undeploy <flow>            # undeploy all
asya flow status <flow>              # aggregated status
asya flow logs <flow>                # aggregated logs with colored actor-name prefix
```

#### Actor Operations (deployment unit)

```bash
asya actor list                      # list actors
asya actor deploy <actor>            # deploy single actor
asya actor undeploy <actor>          # undeploy
asya actor status <actor>            # replicas, queue depth
asya actor logs <actor>              # stream logs
```

#### Message Operations (low-level, direct to queue)

```bash
asya msg send <actor-or-flow> '{}'   # send message to queue
asya msg trace <message-id>          # distributed trace
asya msg replay <message-id>         # replay failed message
asya msg inspect <actor>             # peek at queue/DLQ
asya msg drain <actor>               # drain DLQ
```

#### Project / Infrastructure

```bash
asya init                            # scaffold project
asya serve                           # start local HTTP/WS server for UI
asya context list                    # list contexts
asya context use <name>              # switch context
asya compile                         # shortcut: compile all flows
```

### 3.2 Context System

All commands respect context, resolved in this order (highest priority first):

1. `--context` flag on the command
2. `ASYA_CONTEXT` environment variable
3. Default context in `asya.yaml`

Contexts are defined in `asya.yaml`:

```yaml
# asya.yaml
project: my-project
default_context: docker

contexts:
  docker:
    type: docker-compose
    compose_file: deploy/docker-compose.yaml

  k8s-stg:
    type: kubernetes
    namespace: staging
    kubeconfig: ~/.kube/config
    context: stg-cluster

  k8s-prod:
    type: kubernetes
    namespace: production
    kubeconfig: ~/.kube/config
    context: prod-cluster
```

All `asya.yaml` values are overridable by `ASYA_*` environment variables:

```bash
export ASYA_CONTEXT=k8s-stg
export ASYA_NAMESPACE=my-namespace
```

Alias pattern for convenience:

```bash
alias astg="asya --context=k8s-stg"
alias aprod="asya --context=k8s-prod"
```

### 3.3 Protocol Handling

`asya flow call` and `asya flow expose` accept a `--protocol=mcp|a2a` flag.
The default protocol is configurable in `asya.yaml`:

```yaml
gateway:
  protocol: mcp  # or a2a
  url: http://localhost:8080
```

Data scientists should not need to care about MCP vs A2A. Both are gateway front
doors that accept the same payload and return the same results. The protocol
selection is a deployment concern, not a user concern.

### 3.4 Log Display

`asya flow logs <flow>` aggregates logs from all actors in the flow, prefixed
with a colored actor name (similar to `docker compose logs`):

```
text-analyzer    | [+] Processing message abc-123
text-analyzer    | [+] Analysis complete
summarizer       | [+] Received input from text-analyzer
summarizer       | [+] Summary generated
```

Each actor gets a distinct color from a fixed palette. The display works for both
K8s (`kubectl logs`) and Docker (`docker compose logs`) backends.

### 3.5 Deploy/Undeploy Semantics

Deployment behavior depends on the active context type:

| Context type | `deploy` | `undeploy` |
|---|---|---|
| `kubernetes` | `kubectl apply` manifests | `kubectl delete` manifests |
| `docker-compose` | `docker compose up -d` | `docker compose down` |

**K8s safety rule**: `asya flow deploy` on K8s checks for an existing deployment.
If a different version exists, the command errors and asks the user to explicitly
undeploy first. If an identical version exists, exit 0 (idempotent). This prevents
accidental overwrites in shared environments.

---

## 4. Jupyter Magics

### 4.1 Basic Usage

```python
%load_ext asya

# Compile and visualize flow
%asya flow compile my_flows/order_processing.py
# -> renders interactive flow diagram inline

# Check status
%asya flow status order-processing --context=k8s-stg

# Call flow (line magic for simple payloads)
%asya flow call analyze '{"text": "hello world"}'

# Call flow (cell magic for complex payloads)
%%asya flow call analyze --context=k8s-stg
{"text": "hello world", "options": {"language": "en"}}

# Stream results
%asya flow stream <task-id>

# Logs
%asya flow logs order-processing
```

The `%asya` line magic and `%%asya` cell magic both delegate to the same SDK
functions. The cell magic variant is useful for multi-line JSON payloads.

### 4.2 Interactive Visualization

Flow compilation renders an interactive graph inline in the notebook cell output:

- Nodes represent actors and routers
- Edges represent message routes
- Clicking an actor node reveals a detail panel showing:
  - Configuration (from actor definition)
  - Environment variables
  - Live logs (if deployed)
  - Replica count and queue depth (if deployed)
- Configuration changes in the detail panel write back to local files

Implementation options (in priority order):

1. **ipywidgets** -- works in JupyterLab and classic Jupyter
2. **JupyterLab extension** -- richer interactivity, JupyterLab only
3. **Static SVG with links** -- fallback for environments without widget support

### 4.3 Rich Output

Jupyter output uses rich formatting where available:

- Status tables with colored status indicators (green/yellow/red)
- Log streaming with actor-name coloring (same palette as CLI)
- Progress bars for long-running operations (reusing existing tqdm-based progress
  from the MCP client)
- Inline error display with tracebacks

---

## 5. Refactoring from asya-cli

### 5.1 Current State

The existing `src/asya-cli/` package contains:

| Module | Lines (approx) | Purpose |
|---|---|---|
| `mcp/client.py` | ~300 | MCP gateway HTTP client |
| `mcp/commands.py` | ~400 | Click commands for MCP operations |
| `mcp/port_forward.py` | ~160 | kubectl port-forward helper |
| `flow/parser.py` | ~500 | AST-based flow parser |
| `flow/grouper.py` | ~600 | Operation grouping into routers |
| `flow/codegen.py` | ~700 | Python code generation |
| `flow/dotgen.py` | ~400 | Graphviz DOT generation |
| `flow/ir.py` | ~80 | IR dataclasses |
| `flow/errors.py` | ~20 | Error classes |
| `flow_cli.py` | ~100 | Flow CLI entry point |
| `cli.py` | ~65 | Main CLI entry point |

### 5.2 Migration Path

The migration preserves all existing functionality while restructuring for SDK use:

1. **Extract core logic** from CLI commands into SDK modules. Each CLI command
   becomes a thin wrapper that calls an SDK function and formats the output.

2. **MCP client** (`asya_cli/mcp/`) moves to `asya/mcp/`. The `MCPClient` class
   becomes the public API. CLI commands in `mcp/commands.py` are rewritten as
   thin wrappers.

3. **Flow compiler** (`asya_cli/flow/`) moves to `asya/compile/frontends/flow_dsl/`.
   The IR dataclasses move to `asya/compile/ir.py`. The compiler API becomes:
   ```python
   from asya.compile import compile_flow
   result = compile_flow("my_flow.py", output_dir="compiled/")
   ```

4. **New modules** are added incrementally:
   - `asya/project/` -- project config loading, actor discovery
   - `asya/deploy/` -- K8s and Docker Compose deployment (requires `[deploy]` extra)
   - `asya/testing/` -- pytest fixtures for VFS and state mocking
   - `asya/server/` -- local HTTP/WS server for UI (requires `[ui]` extra)
   - `asya/jupyter/` -- Jupyter magics (requires `[jupyter]` extra)

5. **Package rename**: `asya-cli` becomes `asya`. The `asya` entry point stays
   the same (`asya = "asya.cli:main"`). The old `asya-cli` package is deprecated.

### 5.3 Backward Compatibility

- The `asya mcp *` commands continue to work unchanged.
- The `asya flow compile` and `asya flow validate` commands continue to work.
- The `asya` CLI entry point does not change.
- The only breaking change is the package name (`asya-cli` -> `asya`).

---

## 6. Local Testing

### 6.1 Pure Python (no framework needed)

Actors are plain Python functions. The simplest test is a direct function call:

```python
from my_actors import analyze

result = analyze({"text": "hello world"})
assert result["sentiment"] == "positive"
```

No special test runner, no Asya infrastructure required. This covers unit-level
actor testing.

### 6.2 Pytest Fixtures (`asya.testing`)

For testing actors that interact with the VFS or state system, the SDK provides
pytest fixtures:

```python
import pytest
from asya.testing import vfs_fixture, message_fixture

def test_router_modifies_route(vfs_fixture):
    """VFS fixture creates /proc/asya/msg/ on disk."""
    vfs_fixture.set_route(prev=[], curr="router-1", next=["actor-a", "actor-b"])

    from my_routers import start_router
    result = start_router({"type": "express"})

    assert vfs_fixture.get_route_next() == ["express-handler", "actor-b"]

def test_actor_with_message(message_fixture):
    """Message fixture creates a properly structured test message."""
    msg = message_fixture.create(
        payload={"text": "hello"},
        route=["analyzer", "summarizer"],
    )
    assert msg["route"]["curr"] == "analyzer"
    assert msg["route"]["next"] == ["summarizer"]
```

### 6.3 Docker Compose Testing

For integration-level testing of full pipelines:

```bash
asya compile --context=docker       # generates docker-compose.yaml
asya flow deploy --context=docker   # runs docker compose up
asya flow call analyze '{"text": "hello"}' --context=docker
asya flow undeploy --context=docker # docker compose down
```

Same CLI verbs as K8s, different context. Tests Dockerfiles and full pipeline
locally before deploying to K8s.

---

## 7. Project Configuration (`asya.yaml`)

The `asya.yaml` file is the single source of truth for project-level configuration:

```yaml
project: my-project
default_context: docker
default_protocol: mcp

gateway:
  url: http://localhost:8080
  protocol: mcp

contexts:
  docker:
    type: docker-compose
    compose_file: deploy/docker-compose.yaml
  k8s-stg:
    type: kubernetes
    namespace: staging
    context: stg-cluster
  k8s-prod:
    type: kubernetes
    namespace: production
    context: prod-cluster

actors:
  # Actor discovery: scan these directories for actor definitions
  scan_dirs:
    - actors/
    - flows/

env_files:
  - .env
  - .env.local
```

**Discovery**: `asya.project.load()` reads `asya.yaml`, discovers actors from
`scan_dirs`, and loads environment variables from `env_files` using `load_dotenv`.

**Override hierarchy** (highest priority first):

1. CLI flags (`--context`, `--namespace`, etc.)
2. Environment variables (`ASYA_CONTEXT`, `ASYA_NAMESPACE`, etc.)
3. `asya.yaml` values
4. Built-in defaults

---

## 8. Related Epics

| Epic | Relationship |
|---|---|
| 1jow (Client UX Design) | Parent design -- this RFC implements the design |
| 1juv (VSCode Extension and Standalone Web) | Sibling -- shares `asya serve` backend |
| 1is3 (GitOps Flow Design) | Informs deploy/undeploy semantics |
| 1ibt (Client Commands deploy/undeploy) | Existing design work absorbed here |
| 1g2t (Gateway Dynamic Tool Exposure) | Powers `asya flow expose` command |
| 1iu4 (Local Testing Workflow) | Informs Docker Compose context |

---

## 9. Scope and Phasing

### Phase 1: Core SDK + CLI restructure

- Package rename (`asya-cli` -> `asya`)
- Extract SDK from CLI (compiler, MCP client)
- Project config (`asya.yaml`, context system)
- Flow and actor commands (list, status, logs)
- `asya init` scaffolding

### Phase 2: Deploy + testing

- `asya flow deploy/undeploy` for K8s and Docker Compose
- `asya actor deploy/undeploy`
- `asya.testing` pytest fixtures (VFS, message, state)
- `asya compile --context=docker` (Docker Compose generation)

### Phase 3: Message operations + Jupyter

- `asya msg send/trace/replay/inspect/drain`
- Jupyter magics (`%asya`, `%%asya`)
- Interactive flow visualization in notebooks
- Rich output formatting

### Phase 4: Server + advanced features

- `asya serve` local HTTP/WS server
- Protocol-agnostic `asya flow call` (MCP + A2A)
- Distributed tracing via `asya msg trace`

---

## 10. Open Questions

1. **Package name conflict**: Is `asya` available on PyPI? If not, alternatives:
   `asya-sdk`, `asya-framework`, `asya-mesh`.

2. **Click vs argparse**: The current CLI uses argparse. Should the new CLI use
   Click (richer features, better subcommand support) or stay with argparse
   (fewer dependencies)?

3. **Jupyter widget framework**: ipywidgets vs JupyterLab extensions vs static
   SVG. Depends on target Jupyter environment.

4. **Docker Compose generation**: Should `asya compile --context=docker` generate
   a full `docker-compose.yaml` or a partial overlay that extends a base compose
   file?
