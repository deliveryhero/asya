# RFC: Client UX Design - Asya Developer Experience

## Summary

This RFC defines the architecture and UX design for the Asya client layer:
a unified developer experience across CLI, Jupyter, VSCode, and standalone web
for interacting with Asya actor meshes. The central design principle is that
the Python SDK (`asya` package) is the single source of truth for all logic.
Every surface is a thin wrapper over the SDK.

## Motivation

Data scientists and ML engineers need to build, deploy, and observe actor
pipelines without becoming Kubernetes experts. The current tooling (CLI for
MCP gateway interaction, flow compiler) is fragmented across separate
components. A unified client layer provides:

- One mental model across all surfaces (CLI, notebook, IDE, browser)
- Lab-to-prod workflow with GitOps promotion via PR review
- Local-first state that is fully git-committable
- Context-aware commands that work identically against staging, prod, or local Docker

---

## 1. Architecture

### 1.1 Core Principle

The Python SDK (`asya` package) is the single source of truth for all logic.
Every CLI command maps 1:1 to an SDK function. Jupyter magics call the SDK
directly. The VSCode extension and standalone web talk HTTP to a local Python
server (`asya serve`). React components (TypeScript) are visuals only -- no
business logic lives in TypeScript.

### 1.2 Surface Topology

```
                    +------------------+
                    |   Python SDK     |  (all logic here)
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
     CLI (thin)        Jupyter magics     asya serve
     wraps SDK         wraps SDK          (FastAPI/Starlette)
                                               |
                                     +---------+---------+
                                     |                   |
                               VSCode ext          Standalone web
                               (React webview)     (React SPA)
```

### 1.3 TS-Python Bridge

- VSCode extension spawns `asya serve` as a subprocess on activation,
  communicates via HTTP/WebSocket.
- VSCode webviews (React) are sandboxed -- they communicate with the
  extension host via `postMessage`. The extension host relays to `asya serve`.
- Standalone web uses the exact same `asya serve` HTTP server directly.
- Jupyter calls the SDK directly (Python-native, no HTTP layer).

### 1.4 Package Extras

```bash
pip install asya            # Core SDK: compiler, project config, MCP client
pip install asya[ui]        # + FastAPI server for VSCode/web
pip install asya[jupyter]   # + Jupyter magic functions
pip install asya[deploy]    # + K8s/Docker interaction (kubectl, helm)
```

### 1.5 Package Layout

```
asya/
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
├── jupyter/              # [jupyter] Magic functions
├── deploy/               # [deploy] K8s/Docker interaction
└── cli/                  # CLI entry point (thin wrapper)
```

State lives in local files (`asya.yaml`, `actor.yaml`, `.env` files) -- all
git-committable. No external databases, no daemon state.

---

## 2. Layered Compiler

Three stages: frontends parse inputs, IR normalizes, backends emit outputs.

### 2.1 Intermediate Representation (IR)

The IR is the AsyncActor XR spec -- minimal, business-only fields. It is NOT
a full CRD. Flavors stay as references (not expanded -- Crossplane resolves
them at deploy time).

### 2.2 Frontends

Three input formats, all producing the same IR:

| Frontend | Use Case |
|---|---|
| Simplified YAML (`actor.yaml` from `deploy/`) | Primary DS-facing format |
| Full CRD | Escape hatch for platform engineers |
| Flow DSL | Existing compiler (Python function syntax) |

### 2.3 Backends (External to Compiler)

The compiler outputs a manifest (IR). Backends are separate adapters that
consume the manifest:

- **`asya-flow` Helm chart** -- Framework-provided, generic chart that consumes
  the manifest as `values.yaml`. Uses `{{ range }}` to loop over actors.
- **`asya render`** -- Generates plain CRD YAML files from the manifest.
- **Future**: Kustomize adapter, etc.

Backend selection is configured in `asya.yaml` under `contexts`.

### 2.4 Flow Compilation

A flow with many steps generates many router actors. These are packaged as one
`manifest.yaml`, not individual CRD files per router:

- All routers share one ConfigMap containing `routers.py`
- Each router actor points to a different handler function within that ConfigMap
- Actors are grouped via labels:
  - `asya.sh/flow=<name>`
  - `asya.sh/flow-role=entrypoint|router|processor|exitpoint`

### 2.5 Manifest (IR) Format

```yaml
# deploy/flows/order-processing/manifest.yaml
flow: order-processing
description: "Process and validate customer orders"

routers:
  - name: start-order-processing
    handler: _routers.start_order_processing
    role: entrypoint
  - name: router-line-4-if
    handler: _routers.router_line_4_if
    role: router

processors:
  - handler: my_actors.text_analyzer.analyze
  - handler: my_actors.payment.process

code:
  _routers.py: |
    ... generated router code ...
```

---

## 3. Actor Identity

### 3.1 Code IS the Actor Card

There is no `actor.yaml` inside Python packages. The handler function itself
carries identity through:

- Import path (e.g., `my_actors.text_analyzer.analyze`)
- Docstring (description)
- Type hints (input/output schema)
- Environment variable defaults (`os.environ.get("X", default)`)

### 3.2 Separation of Concerns

- `src/` contains Python code (pip-installable, cross-referenceable).
  Handler functions are pure business logic.
- `deploy/` contains deployment configuration: `actor.yaml` files that specify
  actor name, transport, flavors, scaling, and environment overrides.
- One handler can be deployed as multiple actors with different names and configs.

---

## 4. Project Structure

```
my-project/                          # One repo = one cluster
├── asya.yaml                        # Project config (contexts, defaults)
│
├── src/                             # Python packages (pip-installable)
│   ├── my_actors/                   # Actor handlers
│   │   ├── pyproject.toml
│   │   └── my_actors/
│   │       ├── text_analyzer.py     # def analyze(p: dict) -> dict: ...
│   │       └── payment.py
│   └── my_flows/                    # Flow definitions
│       ├── pyproject.toml           # depends on my-actors
│       └── my_flows/
│           └── order_processing.py  # from my_actors.text_analyzer import analyze
│
├── deploy/                          # Deployment config (NOT pip-installable)
│   ├── actors/
│   │   └── text-analyzer/
│   │       ├── actor.yaml           # name, handler, flavors, transport
│   │       ├── .env.stg
│   │       └── .env.prod
│   └── flows/
│       └── order-processing/
│           └── manifest.yaml        # asya compile output (the IR)
│
└── .asya/                           # Local-only state (gitignored)
    └── cache/
```

Key distinctions:

- `src/` = Python code. Pip-installable, cross-referenceable between packages.
- `deploy/` = Infrastructure config. Git-committed, environment-specific.
- Compilation output paths are configured in `asya.yaml` and separated from
  user code.

---

## 5. Environment Variables

### 5.1 Namespace Convention

- **`ASYA_*` prefixed** = framework internals (set by the injector at deploy
  time). Never appear in user configuration files.
- **Everything else** = business logic. Handlers use standard
  `os.environ.get("X", "default")` -- no framework-imposed config pattern.

### 5.2 `.env` File Management

- Loaded via standard `load_dotenv` (industry standard).
- Resolution order configurable in `asya.yaml` (see section 6).
- `.env.local` is gitignored for local development secrets.
- In Kubernetes, secrets use `SecretRef` -- no plaintext secrets in git.

### 5.3 Future Consideration

Research on DS config management patterns (Kedro, Hydra, Dagster,
OmegaConf) is deferred. When Asya matures and user feedback accumulates,
consider OmegaConf/Hydra integration for advanced config interpolation.

---

## 6. asya.yaml (Project Configuration)

```yaml
project: my-ml-platform

contexts:
  k8s-stg:
    type: kubernetes
    namespace: ml-stg
    gateway: https://gateway.stg.internal
    compilePath: deploy/k8s/stg/
  k8s-prod:
    type: kubernetes
    namespace: ml-prod
    gateway: https://gateway.prod.internal
    compilePath: deploy/k8s/prod/
  docker:
    type: docker-compose
    compilePath: deploy/docker/

actorDefaults:
  transport: sqs
  flavors: [base]

dotenv:
  stg: [.env, .env.stg]
  prod: [.env, .env.prod]
  local: [.env, .env.local]  # .env.local gitignored
```

All values are overridable by `ASYA_*` env vars (e.g., `ASYA_CONTEXT=k8s-stg`)
and CLI `--options` flags.

---

## 7. CLI Commands

Commands are organized by Asya's core domain abstractions: flow, actor, msg.

### 7.1 Flow Operations (Primary DS Abstraction)

```bash
asya flow compile <flow.py>          # Compile flow -> manifest
asya flow list                       # List all flows (exposed and not)
asya flow expose <flow>              # Register with gateway
asya flow call <flow> '{params}'     # Call via gateway
asya flow stream <id>                # Stream results
asya flow deploy <flow>              # Deploy all actors in flow
asya flow undeploy <flow>            # Undeploy all
asya flow status <flow>              # Aggregated status (all actors)
asya flow logs <flow>                # Aggregated logs (colorful actor-name prefix)
```

### 7.2 Actor Operations (Deployment Unit)

```bash
asya actor list                      # List actors
asya actor deploy <actor>            # Deploy single actor
asya actor undeploy <actor>          # Undeploy
asya actor status <actor>            # Replicas, queue depth
asya actor logs <actor>              # Stream logs
```

### 7.3 Message Operations (Low-Level, Direct to Queue)

```bash
asya msg send <actor-or-flow> '{}'   # Send message to queue
asya msg trace <message-id>          # Distributed trace across actors
asya msg replay <message-id>         # Replay failed message
asya msg inspect <actor>             # Peek at queue/DLQ
asya msg drain <actor>               # Drain DLQ
```

### 7.4 Project and Infrastructure Commands

```bash
asya init                            # Scaffold project
asya serve                           # Start local HTTP/WS server for UI surfaces
asya context list                    # List contexts
asya context use <name>              # Switch context
asya compile                         # Shortcut: compile all flows for all contexts
```

### 7.5 Protocol Handling

- `asya flow call` and `asya flow expose` accept a `--protocol=mcp|a2a` flag.
- Default protocol is configurable in `asya.yaml`.
- Data scientists should NOT care about MCP vs A2A -- both are gateway front
  doors to the same async pipeline.
- Protocol is a gateway config concern, not a CLI concern.

### 7.6 Context Awareness

- All commands respect `ASYA_CONTEXT` env var or `--context` flag.
- `asya compile` generates artifacts for all configured contexts by default,
  or for a specific one with `--context=k8s-stg`.
- Alias pattern: `alias astg="asya --context=k8s-stg"` then `astg flow deploy ...`

### 7.7 Deploy/Undeploy Semantics

- `asya flow deploy` on k8s: `kubectl apply` (error if different version
  exists, exit 0 if identical).
- `asya flow deploy` on docker: `docker compose up -d`.
- `asya actor deploy` / `asya actor undeploy` follow the same pattern.
- Deploy verbs (not up/down) are intentional for K8s safety.

### 7.8 Log Display

- `asya flow logs <flow>` from K8s displays with colorful actor-name prefix
  (like `docker compose logs`).
- `asya actor logs <actor>` streams single actor logs.
- Future: `asya msg trace <id>` for distributed tracing across actors via
  observability tools.

---

## 8. UI Surfaces

### 8.1 Jupyter Magics

```python
%load_ext asya

%asya flow compile my_flows/order_processing.py
# Renders flow diagram inline with clickable nodes

%asya flow status --context=k8s-stg
# Shows actor status, replicas, queue depths

%%asya flow call analyze
{"text": "hello world"}
# Streams result inline

%asya flow logs order-processing
# Streams aggregated logs
```

Interactive flow visualization: compiled graph rendered inline, nodes
clickable to read/write actor configuration, view logs, see replica count.

### 8.2 VSCode Extension

- Starts `asya serve` as subprocess on activation.
- React webview panels: flow diagram viewer (clickable nodes), actor status
  dashboard, log streamer.
- `postMessage` API between webview and extension host.
- Extension host relays to `asya serve` via HTTP/WS.

### 8.3 Standalone Web (`asya serve`)

- Same React components as the VSCode extension.
- Runs on localhost, talks to the Python SDK via HTTP/WS.
- For users without VSCode.
- `asya serve` is always local but context-aware (shows data from the
  current context).

---

## 9. GitOps Workflow

### 9.1 Lab Mode (Imperative -- Staging/Experimentation)

1. DS writes flow code in `src/my_flows/`.
2. DS writes handler code in `src/my_actors/`.
3. `asya flow compile` generates manifest to `deploy/flows/`.
4. `asya flow deploy --context=k8s-stg` deploys to staging.
5. `asya flow call` / `asya msg send` to test.
6. `asya flow logs` / `asya actor status` to observe.
7. Iterate.

### 9.2 Prod Mode (Declarative -- via GitOps)

1. DS commits `deploy/` files to git.
2. PR reviewed by platform engineers.
3. ArgoCD/FluxCD picks up `deploy/` and applies to prod.
4. No imperative writes to prod -- rely on K8s RBAC for enforcement.
5. DS can still observe prod: `asya flow status --context=k8s-prod`,
   `asya flow logs`, `asya flow call`.

### 9.3 DS Configuration Interaction

Data scientists need to read and write actor configuration through the UI
(Jupyter clickable nodes, VSCode panels). The UX flow:

1. Changes in the UI write back to local `deploy/` files (`actor.yaml`, `.env`).
2. DS commits these files to git.
3. PR review by platform engineers.
4. GitOps applies to cluster.

The UX must be simple enough for non-technical DS users.

---

## 10. Shadow / Plug-in-Local

Uses the already-implemented `x-asya-route-override` header mechanism in the
sidecar. This needs a separate detailed RFC. High-level design:

- `asya actor shadow <actor-name>` -- deploy local code as a shadow actor,
  connected to a remote flow.
- Implementation options: new actor with HTTP-to-local sidecar
  (telepresence-style), or local sidecar consuming from queue.
- Use cases: A/B testing, canary deployment, local dataset collection from
  remote flow.
- References: epic 1crb (traffic routing), epic 1fbe (sidecar-runtime
  protocol redesign).

---

## 11. Local Testing

- **Unit testing**: Actors are pure Python functions -- call directly, no
  framework needed.
- **VFS fixtures**: pytest fixtures for `/proc/asya/msg/` (message metadata VFS)
  and `/state/` (stateful actors).
- **Docker Compose testing**: `asya compile --context=docker` generates compose
  files, `asya flow deploy --context=docker` runs `docker compose up`.
- **Same CLI verbs**: Local Docker testing uses identical commands as K8s, just
  a different context.

---

## 12. Future Considerations

- OmegaConf/Hydra integration for advanced config management (when Asya matures).
- Pyodide (Python in WASM) for in-browser flow compilation (no Python install
  needed).
- `asya agent` subgroup if A2A diverges significantly from MCP.
- AsyncFlow CRD if label-based flow management proves insufficient (see ADR
  in epic 1iqd).

---

## 13. Related Epics

| Epic | Title |
|---|---|
| 1jpc | Client CLI and SDK (implementation details) |
| 1juv | VSCode Extension and Standalone Web |
| 1is3 | GitOps Flow Design |
| 1iqd | Flow Workflow Design (ADR: labels vs CRD) |
| 1ibt | Client Commands deploy/undeploy |
| 1crb | Traffic Routing (shadow/plug-in-local) |
| 1c0d | A2A Protocol Compliance |
| 1g2t | Gateway Dynamic Tool Exposure |
| 1iu4 | Local Testing Workflow |
| 1iu5 | Seamless Experimentation Image Building |
