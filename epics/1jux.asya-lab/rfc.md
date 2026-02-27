# RFC: Asya Lab -- Python SDK, CLI, and Jupyter Magics

**Status**: Proposed
**Date**: 2026-02-27
**Epic**: 1jux.asya-lab
**Depends on**: 1jow (client UX design)

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

## 8. Compiler Refactoring

The existing flow compiler in `src/asya-cli/asya_cli/flow/` (parser, grouper,
codegen, dotgen, IR) moves into `asya_lab/compile/frontends/flow_dsl/`. The IR
dataclasses move to `asya_lab/compile/ir.py` as the canonical intermediate
representation shared across all frontends.

New frontends (simplified YAML, CRD) can be added without changing the
compiler core.

---

## 9. MCP Client Refactoring

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

## 10. `asya serve` (UI Extra)

The `[ui]` extra installs FastAPI and bundles the `@asya/ui` React SPA as
static files. `asya serve` starts the local HTTP/WS server consumed by:

- VSCode extension (spawns as subprocess)
- Standalone web (user runs manually)
- asya-lens Docker image (extension spawns inside container)

See epic 1juv for the full `asya serve` API specification.

---

## 11. Jupyter Magics (Jupyter Extra)

```python
%load_ext asya_lab

%asya flow compile order_processing     # renders interactive flow diagram inline
%asya flow status order-processing      # shows actor status table
%asya flow call analyze '{"text": "hello"}'

%%asya flow call analyze                # cell magic for complex payloads
{"text": "hello world", "options": {"language": "en"}}
```

Magics call SDK functions directly (Python-native, no HTTP layer). They
auto-detect project root, resolve flow module names, and render rich output
(tables, graphs, progress bars).

---

## 12. React SPA Bundling

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

## 13. Testing Fixtures (`asya_lab.testing`)

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

## 14. Migration from asya-cli

### 14.1 Current State

The existing `src/asya-cli/` package contains ~3,400 lines: MCP client,
flow compiler, CLI entry points.

### 14.2 Migration Path

1. Create `src/asya-lab/` with new package structure
2. Move MCP client to `asya_lab/mcp/`
3. Move flow compiler to `asya_lab/compile/frontends/flow_dsl/`
4. Add new modules incrementally (project, deploy, testing, server, jupyter)
5. Deprecate `asya-cli` package
6. CLI entry point (`asya`) stays the same

### 14.3 Backward Compatibility

- `asya mcp *` commands continue to work
- `asya flow compile` and `asya flow validate` continue to work
- `asya` CLI entry point does not change
- Only the package name changes (`asya-cli` -> `asya-lab`)

---

## 15. Source Directory

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

## 16. Phasing

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

## 17. Related Epics

| Epic | Relationship |
|---|---|
| 1jow (Client UX Design) | Parent design -- this RFC implements the design |
| 1jpc (Client CLI) | Predecessor; detailed CLI/SDK API design |
| 1juv (Asya UI) | TypeScript workspace; `@asya/ui` bundle goes into `[ui]` extra |
| 1juy (Asya Lens) | Docker image that packages `asya-lab[ui,deploy]` |

---

## 18. Open Questions

1. **Click vs argparse**: Current CLI uses argparse. Should the new CLI use
   Click (richer features, better subcommand support) or stay with argparse?

2. **Jupyter widget framework**: ipywidgets vs JupyterLab extensions vs static
   SVG. Depends on target Jupyter environment.

3. **Docker Compose generation**: Should `asya compile --context=docker` generate
   a full `docker-compose.yaml` or a partial overlay?
