# RFC: Asya Lab -- Python SDK, CLI, and Jupyter Magics

**Status**: Proposed
**Date**: 2026-02-27
**Epic**: 1jux.asya-lab
**Depends on**: 1jow (client UX design)
**Supersedes**: 1jpc (client-cli)

---

## 1. Summary

This RFC defines `asya-lab`, the unified Python package (PyPI) that consolidates
the SDK, CLI, Jupyter magics, and local HTTP server into a single coherent tool.
It replaces the existing `asya-cli` package. The core principle: the SDK is the
single source of truth for all logic; every other surface is a thin wrapper.

---

## 2. Package Naming

`asya` is taken on PyPI. After evaluating alternatives:

| Candidate | Verdict | Reason |
|---|---|---|
| `asya-lab` | **Chosen** | DS-native, signals experimentation and tooling, short |
| `asya-sdk` | Rejected | Generic, forgettable |
| `asya-client` | Rejected | Generic, could be anything |
| `asya-stage` | Rejected | Theater-themed but less intuitive for DS audience |
| `asya-plants` | Rejected | Theater pun; most people think of vegetation |
| `asya-stooge` | Rejected | Funny but unprofessional for a package name |
| `asya-magic` | Rejected | No theater connection, generic |

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

The core install has minimal dependencies (requests, pyyaml, tqdm, graphviz)
and covers the most common workflows: compiling flows, calling the gateway,
and managing project configuration.

### 3.2 Module Layout

```
asya_lab/
├── __init__.py
├── compile/              # Layered compiler
│   ├── frontends/        # Simplified YAML, CRD, Flow DSL
│   ├── ir.py             # Canonical actor spec IR
│   └── backends/         # External adapters (not in compiler)
├── project/              # Project config, actor discovery
│   ├── config.py         # asya.yaml loading
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
# pyproject.toml
[project.scripts]
asya = "asya_lab.cli:main"
```

The CLI binary is still `asya` (short, familiar). Only the package name on
PyPI is `asya-lab`.

---

## 4. SDK API

The SDK exposes a domain-oriented API organized by abstraction level:

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

Each namespace (`asya.flow`, `asya.actor`, `asya.msg`, `asya.context`,
`asya.project`) is a module with public functions. No singleton state --
context is passed explicitly or loaded from `asya.yaml` / `ASYA_CONTEXT`.

---

## 5. CLI Commands

Commands are organized by domain abstractions: flow, actor, msg.

### 5.1 Flow Operations (primary DS abstraction)

```bash
asya flow compile <flow.py>          # compile flow -> manifest
asya flow list                       # list all flows
asya flow expose <flow>              # register with gateway
asya flow call <flow> '{params}'     # call via gateway
asya flow stream <id>                # stream results
asya flow deploy <flow>              # deploy all actors in flow
asya flow undeploy <flow>            # undeploy all
asya flow status <flow>              # aggregated status
asya flow logs <flow>                # aggregated logs (colored actor-name prefix)
```

### 5.2 Actor Operations (deployment unit)

```bash
asya actor list                      # list actors
asya actor deploy <actor>            # deploy single actor
asya actor undeploy <actor>          # undeploy
asya actor status <actor>            # replicas, queue depth
asya actor logs <actor>              # stream logs
```

### 5.3 Message Operations (low-level, direct to queue)

```bash
asya msg send <actor-or-flow> '{}'   # send message to queue
asya msg trace <message-id>          # distributed trace
asya msg replay <message-id>         # replay failed message
asya msg inspect <actor>             # peek at queue/DLQ
asya msg drain <actor>               # drain DLQ
```

### 5.4 Project / Infrastructure

```bash
asya init                            # scaffold project
asya serve                           # start local HTTP/WS server for UI
asya context list                    # list contexts
asya context use <name>              # switch context
asya compile                         # shortcut: compile all flows
```

### 5.5 Protocol Handling

`asya flow call` and `asya flow expose` accept a `--protocol=mcp|a2a` flag.
The default protocol is configurable in `asya.yaml`:

```yaml
gateway:
  protocol: mcp  # or a2a
  url: http://localhost:8080
```

Data scientists should not need to care about MCP vs A2A. Both are gateway
front doors that accept the same payload and return the same results. The
protocol selection is a deployment concern, not a user concern.

### 5.6 Log Display

`asya flow logs <flow>` aggregates logs from all actors in the flow, prefixed
with a colored actor name (similar to `docker compose logs`):

```
text-analyzer    | [+] Processing message abc-123
text-analyzer    | [+] Analysis complete
summarizer       | [+] Received input from text-analyzer
summarizer       | [+] Summary generated
```

Each actor gets a distinct color from a fixed palette. The display works for
both K8s (`kubectl logs`) and Docker (`docker compose logs`) backends.

### 5.7 Deploy/Undeploy Semantics

Deployment behavior depends on the active context type:

| Context type | `deploy` | `undeploy` |
|---|---|---|
| `kubernetes` | `kubectl apply` manifests | `kubectl delete` manifests |
| `docker-compose` | `docker compose up -d` | `docker compose down` |

**K8s safety rule**: `asya flow deploy` on K8s checks for an existing
deployment. If a different version exists, the command errors and asks the
user to explicitly undeploy first. If an identical version exists, exit 0
(idempotent). This prevents accidental overwrites in shared environments.

---

## 6. Context System

All commands respect context, resolved in this order (highest priority first):

1. `--context` flag on the command
2. `ASYA_CONTEXT` environment variable
3. Default context in `asya.yaml`

Alias pattern for convenience:
```bash
alias astg="asya --context=k8s-stg"
alias aprod="asya --context=k8s-prod"
```

---

## 7. Project Configuration (`asya.yaml`)

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
  scan_dirs:
    - actors/
    - flows/

env_files:
  - .env
  - .env.local
```

Override hierarchy (highest priority first):
1. CLI flags (`--context`, `--namespace`, etc.)
2. Environment variables (`ASYA_CONTEXT`, `ASYA_NAMESPACE`, etc.)
3. `asya.yaml` values
4. Built-in defaults

---

## 8. Flow Deployment (Label-Based, No AsyncFlow CRD)

Flow deployment uses **labels + CLI tooling** rather than a separate AsyncFlow
CRD (see ADR in epic 1iqd). The CLI manages flow membership via Kubernetes
labels.

### 8.1 Label Convention

Every actor in a flow carries these labels:

| Label | Purpose | Values |
|---|---|---|
| `asya.sh/flow` | Flow membership (1:M) | Flow name (e.g., `order-processing`) |
| `asya.sh/flow-role` | Role within flow | `entrypoint`, `exitpoint`, `router`, `processor` |

Annotations for gateway metadata:
- `asya.sh/flow-tool` -- MCP tool name (if exposed via gateway)
- `asya.sh/flow-description` -- Tool description (from flow.py docstring)

### 8.2 1:M Constraint

One actor can belong to **at most one flow**. If the same handler logic is
needed in multiple flows, the actor is cloned (new name, same image/handler,
flow-specific scaling config). This makes `asya.sh/flow` a reliable foreign
key and aligns with Kubernetes-native patterns -- different flows need
different scaling/resources.

### 8.3 What `asya flow deploy` Does (K8s context)

1. **Creates AsyncActor manifests for routers** -- new resources with
   `asya.sh/flow` and `asya.sh/flow-role=router` labels.
2. **Updates existing processor actor manifests** -- adds `asya.sh/flow`
   label and `asya.sh/flow-role=processor`.
3. **Marks entrypoint/exitpoint actors** -- sets `asya.sh/flow-role`
   accordingly.
4. **Creates ConfigMap with router code** -- `routers.py` content, labeled
   with `asya.sh/flow`. All routers in the flow share this ConfigMap.
5. Supports `--output-dir` for GitOps (generate files to disk instead of
   applying).

### 8.4 What `asya flow undeploy` Does (K8s context)

Removes all flow resources by label:
`kubectl delete asya,configmap -l asya.sh/flow=<name>`.

Option `--keep-processors` deletes only routers and ConfigMap, preserving
processor actors (useful when processor actors are shared infrastructure).

### 8.5 Router Flavors

Generated router actors are lightweight (pure Python routing logic, no ML
models). Platform engineers can define a `flow-router` flavor with minimal
resources:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: flow-router
  labels:
    asya.sh/flavor: flow-router
data:
  scaling:
    minReplicas: 0
    maxReplicas: 20
  workload:
    template:
      spec:
        containers:
        - name: asya-runtime
          resources:
            requests: { cpu: "50m", memory: "64Mi" }
            limits: { cpu: "200m", memory: "128Mi" }
```

`asya flow compile --router-flavor flow-router` auto-injects the flavor
reference into all generated router actors in the manifest.

---

## 9. Flow Exposure (`asya flow expose`)

Registers a flow as an MCP tool (or A2A agent) in the gateway's singleton
ConfigMap (`gateway-tools`):

1. Finds entrypoint actor by label: `asya.sh/flow-role=entrypoint`
2. Reads tool metadata from annotations or flow.py (name, description,
   parameters)
3. Patches `gateway-tools` ConfigMap via `kubectl patch`
4. Gateway detects change via fsnotify and reloads tool config (no restart
   needed)

The gateway watches its mounted config directory via fsnotify. Changes to the
ConfigMap propagate through kubelet volume sync and trigger a hot-reload of
the tool registry. Existing in-flight requests complete normally.

Discovery queries work natively via kubectl:
```bash
kubectl get asya -l asya.sh/flow=order-processing
kubectl get asya -l asya.sh/flow-role=entrypoint
```

---

## 10. Compiler Refactoring

The existing flow compiler in `src/asya-cli/asya_cli/flow/` (parser, grouper,
codegen, dotgen, IR) moves into `asya_lab/compile/frontends/flow_dsl/`. The IR
dataclasses move to `asya_lab/compile/ir.py` as the canonical intermediate
representation shared across all frontends.

New frontends (simplified YAML, CRD) can be added without changing the
compiler core.

---

## 11. MCP Client Refactoring

The existing MCP client in `src/asya-cli/asya_cli/mcp/` moves into
`asya_lab/mcp/`. The client becomes a standalone class:

```python
from asya_lab.mcp import MCPClient

client = MCPClient(gateway_url="http://localhost:8080")
tools = client.list_tools()
result = client.call_tool("analyze", {"text": "hello"})
for event in client.stream(result.task_id):
    print(event)
```

---

## 12. `asya serve` (UI Extra)

The `[ui]` extra installs FastAPI and bundles the `@asya/ui` React SPA as
static files. `asya serve` starts the local HTTP/WS server consumed by:

- VSCode extension (spawns as subprocess)
- Standalone web (user runs manually)
- asya-lens Docker image (extension spawns inside container)

See epic 1juv for the full `asya serve` API specification.

---

## 13. Jupyter Magics (Jupyter Extra)

### 13.1 How Magics Work

Jupyter magic functions (`%` for line magics, `%%` for cell magics) are NOT
shell commands (`!`). They are Python extensions that receive the notebook
context and can dynamically process information from the notebook environment:

- The magic extension can inspect locally developed flows and actors
- It can auto-detect the current project, context, and available flows
- It can provide shorter commands by inferring context from the notebook state
- It can render rich interactive output (widgets, graphs, tables)

### 13.2 Basic Usage

```python
%load_ext asya_lab

# Compile and visualize flow -- magic auto-detects project root
%asya flow compile order_processing
# -> renders interactive flow diagram inline in cell output

# Check status -- context from ASYA_CONTEXT or asya.yaml default
%asya flow status order-processing

# Call flow (line magic for simple payloads)
%asya flow call analyze '{"text": "hello world"}'

# Call flow (cell magic for complex payloads)
%%asya flow call analyze
{"text": "hello world", "options": {"language": "en"}}

# Stream results
%asya flow stream <task-id>

# Logs
%asya flow logs order-processing
```

### 13.3 Notebook Context Auto-Processing

The Jupyter magic extension automatically processes the notebook environment:

- **Project detection**: Finds `asya.yaml` from the notebook's working
  directory
- **Flow discovery**: Scans imported modules and local packages for flow
  definitions
- **Variable injection**: If the user defines a `payload` variable in a prior
  cell, magics can reference it: `%asya flow call analyze payload`
- **Context inference**: Reads `ASYA_CONTEXT` or notebook-level configuration
- **Shorter commands**: Because the magic knows the project context, users can
  write `%asya flow compile order_processing` instead of the full module path

This context awareness is what makes `%` magics fundamentally different from
`!` shell commands.

### 13.4 Interactive Visualization

Flow compilation renders an interactive graph inline in the notebook cell
output:

- Nodes represent actors and routers
- Edges represent message routes
- Clicking an actor node reveals a detail panel showing:
  - Configuration (from actor.yaml in deploy/)
  - Environment variables
  - Live logs (if deployed)
  - Replica count and queue depth (if deployed)
- Configuration changes in the detail panel write back to local deploy/ files
- Same interactive components as VSCode extension (shared React components
  rendered via ipywidgets or JupyterLab widget framework)

Implementation options (in priority order):

1. **ipywidgets** -- works in JupyterLab and classic Jupyter
2. **JupyterLab extension** -- richer interactivity, JupyterLab only
3. **Static SVG with links** -- fallback for environments without widget
   support

### 13.5 Rich Output

Jupyter output uses rich formatting where available:

- Status tables with colored status indicators (green/yellow/red)
- Log streaming with actor-name coloring (same palette as CLI)
- Progress bars for long-running operations (reusing existing tqdm-based
  progress from the MCP client)
- Inline error display with tracebacks

---

## 14. React SPA Bundling

The `@asya/ui` React components (from epic 1juv) are built into a JS bundle
and copied into `asya_lab/server/static/` as part of the Python package build.

Build pipeline:
```
src/asya-ui/packages/components/ -> pnpm build -> dist/
dist/ -> copy to src/asya-lab/asya_lab/server/static/
src/asya-lab/ -> uv build -> asya-lab wheel (includes static/)
```

The `[ui]` extra adds the FastAPI dependency; the static files are always
included in the wheel but only served when FastAPI is installed.

---

## 15. Testing Fixtures (`asya_lab.testing`)

Pytest fixtures for testing actor handlers:

```python
from asya_lab.testing import vfs_fixture, message_fixture

def test_router_modifies_route(vfs_fixture):
    vfs_fixture.set_route(prev=[], curr="router-1", next=["actor-a", "actor-b"])
    from my_routers import start_router
    result = start_router({"type": "express"})
    assert vfs_fixture.get_route_next() == ["express-handler", "actor-b"]
```

---

## 16. Local Testing

### 16.1 Pure Python (no framework needed)

Actors are plain Python functions. The simplest test is a direct function
call:

```python
from my_actors import analyze

result = analyze({"text": "hello world"})
assert result["sentiment"] == "positive"
```

No special test runner, no Asya infrastructure required.

### 16.2 Docker Compose Testing

For integration-level testing of full pipelines:

```bash
asya compile --context=docker       # generates docker-compose.yaml
asya flow deploy --context=docker   # runs docker compose up
asya flow call analyze '{"text": "hello"}' --context=docker
asya flow undeploy --context=docker # docker compose down
```

Same CLI verbs as K8s, different context.

---

## 17. Migration from asya-cli

### 17.1 Current State

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

### 17.2 Migration Path

1. Create `src/asya-lab/` with new package structure
2. Move MCP client to `asya_lab/mcp/` -- `MCPClient` becomes the public API;
   CLI commands rewritten as thin wrappers
3. Move flow compiler to `asya_lab/compile/frontends/flow_dsl/` -- IR
   dataclasses to `asya_lab/compile/ir.py`
4. Add new modules incrementally (project, deploy, testing, server, jupyter)
5. Deprecate `asya-cli` package
6. CLI entry point (`asya`) stays the same

### 17.3 Backward Compatibility

- `asya mcp *` commands continue to work
- `asya flow compile` and `asya flow validate` continue to work
- `asya` CLI entry point does not change
- Only the package name changes (`asya-cli` -> `asya-lab`)

---

## 18. Source Directory

```
src/asya-lab/
├── pyproject.toml
├── asya_lab/
│   ├── __init__.py
│   ├── compile/
│   ├── project/
│   ├── mcp/
│   ├── testing/
│   ├── server/
│   ├── jupyter/
│   ├── deploy/
│   └── cli/
└── tests/
```

---

## 19. Phasing

### Phase 1: Core SDK + CLI restructure
- Package creation, migration from asya-cli
- SDK extraction (compiler, MCP client)
- Project config (asya.yaml, context system)
- Flow and actor commands (list, status, logs)
- `asya init` scaffolding

### Phase 2: Deploy + testing
- `asya flow deploy/undeploy` for K8s and Docker Compose
- `asya actor deploy/undeploy`
- `asya_lab.testing` pytest fixtures
- `asya compile --context=docker`

### Phase 3: Message operations + Jupyter
- `asya msg send/trace/replay/inspect/drain`
- Jupyter magics
- Interactive flow visualization in notebooks

### Phase 4: Server + advanced features
- `asya serve` local HTTP/WS server
- Protocol-agnostic `asya flow call` (MCP + A2A)

---

## 20. Related Epics

| Epic | Relationship |
|---|---|
| 1jow (Client UX Design) | Parent design -- this RFC implements the design |
| 1jpc (Client CLI) | Superseded by this RFC |
| 1juv (Asya UI) | TypeScript workspace; `@asya/ui` bundle goes into `[ui]` extra |
| 1juy (Asya Lens) | Docker image that packages `asya-lab[ui,deploy]` |
| 1is3 (GitOps Flow Design) | Informs deploy/undeploy semantics |
| 1ibt (Client Commands) | Existing design work absorbed here |
| 1g2t (Gateway Dynamic Tool Exposure) | Powers `asya flow expose` command |
| 1iu4 (Local Testing Workflow) | Informs Docker Compose context |

---

## 21. Open Questions

1. **Click vs argparse**: Current CLI uses argparse. Should the new CLI use
   Click (richer features, better subcommand support) or stay with argparse?

2. **Jupyter widget framework**: ipywidgets vs JupyterLab extensions vs static
   SVG. Depends on target Jupyter environment.

3. **Docker Compose generation**: Should `asya compile --context=docker`
   generate a full `docker-compose.yaml` or a partial overlay?
