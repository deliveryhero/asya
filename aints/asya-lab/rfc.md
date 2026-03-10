# RFC: Asya Lab -- Python SDK, CLI, and Jupyter Magics

**Status**: Proposed (revised 2026-03-09)
**Date**: 2026-02-27 (original), 2026-03-08 (revised), 2026-03-09 (kustomize-native, k/d split, three-layer kustomize)
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
│   ├── kustomize.py      # kustomization.yaml generation, patch management
│   └── rules.py          # treat-as rules engine
├── compose/              # Docker Compose translator (XR → docker-compose.yaml)
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

# --- Compile (local, no cluster) ---
asya.compile("my_flows/order_processing.py")
asya.compile("e_commerce.validate.validate_order")  # single actor

# --- K8s Operations ---
asya.k.apply("order-processing", context="k8s-stg")
asya.k.delete("order-processing", context="k8s-stg")
asya.k.status("order-processing")
asya.k.logs("order-processing")
asya.k.call("analyze", {"text": "hello"}, protocol="mcp")
asya.k.stream(task_id)
asya.k.send("text-analyzer", {"text": "hello"})

# --- Docker Operations ---
asya.d.up("my_flows/order_processing.py")  # auto-compile + compose + up
asya.d.down("order-processing")
asya.d.send("text-analyzer", {"text": "hello"})

# --- Project ---
asya.k.context.use("k8s-stg")
config = asya.project.load()
```

Each namespace is a module with public functions. No singleton state -- context
is passed explicitly or loaded from `.asya/config.yaml` / `ASYA_CONTEXT`.

---

## 5. CLI Commands

Commands are organized by interaction target: top-level (local only),
`k` (Kubernetes), `d` (Docker). The flow/actor distinction is removed --
the CLI auto-detects whether the target is a flow or single actor.

See `adr.k-d-command-split.md` for the rationale.

### 5.1 Top-Level Commands (Local Only)

```bash
asya compile <target>               # Python -> manifests + routers (no cluster needed)
asya expose <target>                # generate gateway ConfigMap in base/ (no cluster needed)
asya show <target> [--context ctx]  # kustomize build -> effective manifests (no cluster needed)
asya status                         # local source of truth (compiled manifests, CRs)
asya init [--template <name>]       # scaffold .asya/ via Copier
asya serve                          # start local HTTP/WS server for UI
```

`asya compile` auto-detects the target type:

| Input | Detection | Behavior |
|-------|-----------|----------|
| `myflow.py` | File exists, `.py` extension | Compile flow from source |
| `e_commerce.validate.process` | Dotted path, no file | Compile single actor manifest |
| `order-processing` | Kebab-case name | Recompile from existing manifests |

**Naming flags** (`--flow` and `--actor`):

Both flags accept a single name (when unambiguous) or a `<source>=<name>` mapping:

```bash
# Auto-derive all names (kebab-case from function names)
asya compile order.py

# Override flow name (one @flow per file, unambiguous)
asya compile order.py --flow my-order-flow

# Override single actor name (errors if multiple @actor in file)
asya compile handler.py --actor my-handler

# Explicit mapping (repeatable, source can be function name or FQN)
asya compile order.py --flow my-flow \
  --actor validate_order=validator \
  --actor e_commerce.processing.express_handler=express
```

Default names are derived from function names via kebab-case conversion
(`order_processing` -> `order-processing`). Unspecified actors keep their
auto-derived names; users can rename them later in kustomize overlays.

Both `asya compile` and `asya expose` are idempotent — re-running overwrites
previous output cleanly.

### 5.2 Kubernetes Commands (`asya k`)

```bash
asya k edit <actor-name>            # open kustomize patch in common/ for actor
asya k build <target>               # build + push images to registry
asya k apply <target>               # auto-compile if .py, kustomize build | kubectl apply --server-side
asya k delete <target>              # kubectl delete
asya k status <target>              # live cluster state: replicas, queue depth
asya k logs <target>                # kubectl logs (colored per-actor)
asya k call <target> '{}'           # call via gateway
asya k stream <id>                  # stream results via gateway SSE
asya k send <target> '{}'           # send envelope to queue
asya k trace <id>                   # distributed trace
asya k secret create|remove|list|show  # K8s secretKeyRef mappings
asya k context list|use             # switch K8s context
```

Aliases: `asya k` = `asya k8s` = `asya kubernetes`.

`asya k apply` auto-compiles when given a `.py` file:
```
$ asya k apply flows/order.py --context stg
[compile] 4 actors, 2 routers → .asya/manifests/order-processing/
[apply]   kustomize build .asya/manifests/order-processing/overlays/stg/
[apply]   kubectl apply --server-side --field-manager=asya-flow-order-processing -f -
asyncactor.asya.sh/validate-order serverside-applied
asyncactor.asya.sh/router-start-order-processing serverside-applied
configmap/gateway-flows serverside-applied
```

### 5.3 Docker Commands (`asya d`)

```bash
asya d up <target>                  # auto-compile + generate compose + docker compose up
asya d down <target>                # docker compose down
asya d send <target> '{}'           # send envelope to socket
asya d logs <target>                # docker compose logs -f
asya d trace <id>                   # trace message
```

Aliases: `asya d` = `asya docker`.

`asya d up` does everything in one shot:
```
$ asya d up flows/order.py
[compile] 4 actors, 2 routers → .asya/manifests/order-processing/
[compose] → .asya/compose/order-processing.yaml (socket transport)
[docker]  docker compose -f .asya/compose/order-processing.yaml up -d
```

**Docker secrets**: When `asya d up` detects env vars mapped to K8s secrets
(via `asya k secret`), it checks `.env.secret`. If missing or incomplete:
```
Error: 2 secrets not in .env.secret (OPENAI_API_KEY, DB_PASSWORD)
  hint: asya k secret show -o env >> .env.secret && chmod 600 .env.secret
  hint: ensure .env.secret is in .gitignore (asya init adds it automatically)
```

### 5.4 File Safety

All commands that generate or modify files refuse to overwrite unless the
target is git-committed. Prevents accidental loss of manual edits.

- `asya compile` → won't overwrite dirty routers.py or base/ manifests
- Override with `--force`

All file-generating commands show the git diff of their changes.

### 5.5 Command Transparency

All CLI commands that execute external tools print what they run, like
`set -x` in shell. Commands are printed to stderr before execution.

This makes every CLI action auditable and reproducible -- the user can
copy-paste the printed commands to run them manually.

### 5.6 Command Data Sources

No CLI command uses the gateway's internal `/mesh/*` routes -- those are
reserved for sidecar-to-gateway communication.

| Command | Backend | Protocol / API |
|---------|---------|---------------|
| `asya compile <target>` | Local | Config + Python resolution |
| `asya expose <target>` | Local | Generate `configmap-flows.yaml` in `base/` |
| `asya show <target>` | Local | `kustomize build` → effective manifests |
| `asya status` | Local | Source of truth from compiled manifests |
| `asya k apply <target>` | K8s | `kustomize build overlay \| kubectl apply --server-side -f -` |
| `asya k delete <target>` | K8s | `kubectl delete` by flow labels |
| `asya k status <target>` | K8s | `kubectl get asyncactor` (live cluster state) |
| `asya k logs <target>` | K8s | `kubectl logs -l asya.sh/flow=<name>` |
| `asya k call <target>` | Gateway | MCP `tools/call` or A2A `message/send` |
| `asya k stream <id>` | Gateway | MCP streamable HTTP or A2A subscribe |
| `asya k send <target>` | MQ | Direct queue publish (SQS/RabbitMQ API) |
| `asya k trace <id>` | Observability | OpenTelemetry trace query |
| `asya k edit <actor>` | Local | Opens/creates kustomize patch file |
| `asya k build <target>` | Build tool | Opaque shell command from config.yaml |
| `asya k secret *` | Local | Reads/writes config.yaml secrets: |
| `asya k context *` | Local | Reads/writes config.yaml contexts: |
| `asya config get <key>` | Local | Read merged config value (dot-path) |
| `asya serve` | Local | Start local API server (FastAPI) |
| `asya d up <target>` | Docker | Compile + compose + `docker compose up -d` |
| `asya d down <target>` | Docker | `docker compose down` |
| `asya d send <target>` | Docker | Write to Unix socket |
| `asya d logs <target>` | Docker | `docker compose logs -f` |

### 5.7 List and Discovery

`asya status` (local) shows a unified outer-join table across two local data
sources: source files and compiled manifests. `asya k status` (cluster) adds
the deployed state column.

**Discovery**: Scan `.py` files under `var.project_root` for `@actor` and
`@flow` decorators, matched against compiler rules.

**Data sources** (joined by name):

| Column | Source | Available when |
|--------|--------|----------------|
| SOURCE | `.py` files with `@flow`/`@actor` decorators | Always (pre-compile) |
| COMPILED | `.asya/manifests/<flow>/` YAML files | After `asya compile` |
| DEPLOYED | K8s `asyncactor` resources | After `asya k apply` |

### 5.8 Protocol Handling

`asya k call` and `asya expose` accept a `--protocol=mcp|a2a` flag.
Default is configurable. DS should not need to care about MCP vs A2A.

### 5.9 Apply Semantics

`asya k apply` runs `kustomize build` on the context-specific overlay
(merges base → common → overlay), pipes effective manifests to
`kubectl apply --server-side` with a per-flow field manager.

```bash
kustomize build .asya/manifests/<flow>/overlays/<context>/ \
  | kubectl apply --server-side --field-manager=asya-flow-<flow> -f -
```

**Server-side apply (SSA)** with per-flow field managers allows multiple flows
to contribute data keys to the shared `gateway-flows` ConfigMap without
conflicts. Each flow's field manager owns only its data key. Since asya fully
manages kubectl, mixed apply mode risks are eliminated.

**Idempotent by design**: `apply` (not `deploy`) signals declarative semantics —
running it twice with the same manifests is a no-op. SSA merges fields rather
than replacing, so `asya k apply` is always safe to re-run.

### 5.10 Read-Only Enforcement

Contexts with `readonly: true` block write operations:
- `asya k apply/delete` → error (production writes happen via GitOps PR)

Read operations always allowed: `status`, `logs`, `call`, `stream`.

### 5.11 Three Testing Tiers

| Tier | What runs | Transport | Command |
|------|-----------|-----------|---------|
| **pytest** | Pure Python function | None (direct call) | `pytest` with `asya_lab.testing` fixtures |
| **Single actor** | Runtime as HTTP server | None (HTTP) | `asya d up <actor.py>` (handler marked with `@actor`) |
| **Full flow** | Sidecar + runtime per actor | Socket | `asya d up <flow.py>` |

Flow functions are valid Python — testable directly with `pytest` before
compilation splits them into actors. No Asya command needed for unit tests.

---

## 6. Context System

A context is a named K8s cluster profile. Contexts are used by `asya k`
commands only. Docker local testing (`asya d`) does not use contexts.

See `adr.k-d-command-split.md` for why Docker is not a context type.

### 6.1 Context Definition

```yaml
# .asya/config.yaml
contexts:
  stg:
    type: kubernetes
    kubecontext: my-stg-cluster     # kubeconfig context name (required)
    namespace: "${var.namespace}"    # K8s namespace
    gateway: https://gw.stg.internal
  prod:
    type: kubernetes
    kubecontext: my-prod-cluster
    namespace: prod
    gateway: https://gw.prod.internal
    readonly: true                  # blocks apply/delete, allows status/logs/call

default_context: stg
```

### 6.2 Fields

- `kubecontext` (required): kubeconfig context name
- `namespace` (required): K8s namespace
- `gateway` (optional): gateway URL for `call`/`stream`
- `readonly` (optional, default `false`): blocks apply/delete

### 6.3 Resolution Order

Highest priority first:

1. `--context` flag on the command
2. `ASYA_CONTEXT` environment variable
3. `default_context` field in config.yaml

**No auto-detection fallback.** If no context is resolved, `asya k` commands
that need a deployment target fail with:
```
Error: no context configured
  hint: add contexts: section to .asya/config.yaml
  hint: or pass --context=<name>
  see: asya init --help
```

`asya compile` and `asya d` commands do not need a context.

### 6.4 CLI

```bash
asya k context list                 # show all contexts, mark active
asya k context use <name>           # set default_context in config.yaml
```

`asya k context list` output:
```
  NAME    NAMESPACE    GATEWAY                      READONLY
* stg     team-one     https://gw.stg.internal      no
  prod    prod         https://gw.prod.internal     yes
```

`asya k context use prod` writes `default_context: prod` to config.yaml.
Committed to git = team-shared default. Per-developer override via
`ASYA_CONTEXT` env var.

### 6.5 Docker Compose Architecture (Socket Transport)

Docker Compose local testing uses the same sidecar architecture as K8s,
with a **socket transport** (`ASYA_TRANSPORT=socket`) instead of SQS/RabbitMQ.

```
┌──────────────┐  unix socket  ┌──────────────┐  mesh socket   ┌──────────────┐
│ Sidecar A    │ ────────────→ │ Runtime A    │                │ Sidecar B    │
│ (asya-sidecar│ ←──────────── │ (user image) │                │              │
│  socket tx)  │               └──────────────┘  ──────────→   │ (listens on  │
│              │ ───────────────────────────────────────────→   │  B.sock)     │
└──────────────┘                                               └──────────────┘
```

Each sidecar listens on `/var/run/asya/mesh/<actor-name>.sock`. A shared
Docker volume makes all mesh sockets visible to all sidecars.

**Generated compose file** (`asya d up flows/order.py`):

```yaml
# .asya/compose/order-processing.yaml
services:
  validate-order:
    image: ghcr.io/org/e-commerce:latest
    command: python /opt/asya/asya_runtime.py
    environment:
      ASYA_HANDLER: e_commerce.validate.validate_order
      ASYA_ACTOR_NAME: validate-order
      ASYA_TRANSPORT: socket
    volumes:
      - runtime-validate:/var/run/asya
      - mesh:/var/run/asya/mesh

  sidecar-validate-order:
    image: ghcr.io/asya-sh/asya-sidecar:latest
    environment:
      ASYA_ACTOR_NAME: validate-order
      ASYA_TRANSPORT: socket
    volumes:
      - runtime-validate:/var/run/asya
      - mesh:/var/run/asya/mesh

  x-sink:
    image: ghcr.io/asya-sh/asya-crew:latest
    environment:
      ASYA_ACTOR_NAME: x-sink
      ASYA_TRANSPORT: socket
    volumes:
      - mesh:/var/run/asya/mesh

volumes:
  mesh:
  runtime-validate:
```

**Socket transport constraints** (acceptable for local testing):
- Single replica per actor (one consumer per socket)
- No queue-level DLQ (sidecar handles errors in-process)
- No KEDA autoscaling
- Sequential FIFO delivery

**State proxy**: Shared volume with optional seed data:
```yaml
  state-proxy:
    volumes:
      - state:/state
      - ./seed-data:/seed:ro    # optional startup hook pre-fills state
```

**Benefits over orchestrator approach** (superseded RFC section 6.2):
- No lossy translation -- same sidecar, same runtime, same envelope protocol
- No new component to build (the orchestrator)
- Socket transport also benefits integration tests (decouple from RabbitMQ/SQS)
- x-sink and x-sump work identically to K8s

**Docker secrets**: Env vars mapped to K8s secrets via `asya k secret` must
be present in `.env.secret` (gitignored, chmod 600). `asya d up` fails with
a hint if any are missing. `asya init` adds `.env.secret` to `.gitignore`.
No dedicated secret commands for Docker -- users populate the file manually:
```bash
asya k secret show -o env >> .env.secret && chmod 600 .env.secret
```

---

## 7. Project Configuration (`.asya/`)

The `.asya/` directory marks the project root (like `.git/`). Created by
`asya init`. Configuration is split across three files, each a separate concern.
All files are loaded into one OmegaConf DictConfig (the library, not
"inspired by") — file boundaries are for human organization.

### 7.1 File Structure

```
.asya/
├── config.yaml              # root: var, build, compiler, secrets, contexts
├── compiler/                # → auto-merged under compiler: key
│   ├── rules.yaml           # → compiler.rules (treat-as rules)
│   └── templates/           # → compiler.templates
│       ├── actor.yaml       # → compiler.templates.actor (AsyncActor CRD)
│       └── kustomization.yaml  # → compiler.templates.kustomization
├── manifests/               # kustomize output (per-flow subdirectories)
│   └── <flow>/
│       ├── base/                # layer 1: compiler output (regenerated)
│       │   ├── kustomization.yaml
│       │   ├── <actor>.yaml     # AsyncActor XRs
│       │   └── configmap-flows.yaml  # gateway exposure (if asya expose ran)
│       ├── common/              # layer 2: shared user customizations (preserved)
│       │   ├── kustomization.yaml    # resources: ../base + patches
│       │   └── <actor>.yaml          # infra-tier patches (scaling, resources, etc.)
│       └── overlays/            # layer 3: per-context overrides
│           ├── stg/
│           │   ├── kustomization.yaml  # resources: ../../common + patches
│           │   └── ...
│           └── prod/
│               ├── kustomization.yaml
│               └── ...
└── compose/                 # docker compose output
    └── <flow>.yaml
```

**Directory-to-key convention**: directories under `.asya/` that match a root
config key have their contents recursively merged under that key. Files become
sub-keys (filename stem = key). Subdirectories create nested keys.

- `.asya/config.yaml` — root keys (always loaded)
- `.asya/compiler/rules.yaml` → `compiler.rules` in merged config
- `.asya/compiler/templates/actor.yaml` → `compiler.templates.actor`

Important user-facing settings (paths, scalars) stay in `config.yaml`.
Complex structured content (rules, templates) is offloaded into directories
for clarity. Both locations merge — you CAN put `compiler.rules` inline in
`config.yaml` for small projects and offload to `compiler/rules.yaml` when
the list grows.

### 7.2 config.yaml

```yaml
var:
  project_root: "."
  image_registry: ghcr.io/org
  namespace: team-one
  transport: sqs
  router_image: python:3.13-slim

build:
  - module: e_commerce
    path: "${var.project_root}/src/e-commerce"
    image: "${var.image_registry}/e-commerce:${arg:tag}"
    command: "docker build -t ${.image} ."

compiler:
  routers: "${var.project_root}/compiled/${dynamic:flow_stem}"
  manifests: ".asya/manifests/${dynamic:flow_stem}"
  # rules and templates auto-merged from .asya/compiler/

secrets:
  OPENAI_API_KEY:
    secret: llm-secrets
    key: openai-api-key
  DB_PASSWORD:
    secret: database-creds
    key: password

contexts:
  stg:
    type: kubernetes
    kubecontext: my-stg-cluster
    namespace: "${var.namespace}"
    gateway: https://gw.stg.internal
  prod:
    type: kubernetes
    kubecontext: my-prod-cluster
    namespace: prod
    gateway: https://gw.prod.internal
    readonly: true
  local:
    type: docker
    compose_output: ".asya/compose/"
    gateway: http://localhost:8080

default_context: stg
```

### 7.3 compiler/templates/actor.yaml

Standalone YAML that looks exactly like the final output — a flat AsyncActor
XR (v1alpha2 spec, see `xrd-v2/rfc.md`). On disk it's a lintable CRD; after
loading it's available as `config.compiler.templates.actor`. The `${dynamic:*}`
holes are filled per-actor during compilation.

```yaml
# .asya/compiler/templates/actor.yaml
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: "${dynamic:actor}"
  namespace: "${var.namespace}"
  labels:
    asya.sh/flow: "${dynamic:flow}"
    asya.sh/flow-role: "${dynamic:flow_role}"
spec:
  actor: "${dynamic:actor}"
  image: "${dynamic:image}"
  handler: "${dynamic:handler}"
  transport: "${var.transport}"
  env: "${dynamic:env}"
  scaling:
    enabled: true
    minReplicas: 0
    maxReplicas: "${arg:max_replicas,5}"
```

The template uses the **flat XRD v2 spec** — `image`, `handler`, `env` are
top-level fields under `spec`, not buried inside
`workload.template.spec.containers[]`. This makes the template trivially
readable and directly maps to what `asya k edit` exposes.

`${dynamic:env}` is an OmegaConf subtree resolver — it returns the full K8s
env list (including `ASYA_HANDLER`, router mappings, and env vars detected from
handler code). See `research-compiler-knowledge-base.md` for how env vars are
detected and sourced via `secrets:`.

**Platform engineers customize the template** to set infra-tier defaults:
```yaml
# Platform team adds to compiler/templates/actor.yaml:
spec:
  # ...
  resiliency:
    retry:
      policy: exponential
      maxAttempts: "${var.default_retry_attempts}"
```

These defaults become part of `base/` and can be overridden per-actor via
kustomize patches.

### 7.3.1 Kustomize Layer Templates

The compiler generates `kustomization.yaml` for each layer. Templates are
stamped once per flow, then updated on subsequent compiles/edits.

**base/kustomization.yaml** (generated by compiler):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: "${dynamic:resources}"
# resources includes AsyncActor YAMLs + configmap-flows.yaml (if exposed)
```

**common/kustomization.yaml** (generated by `asya k edit` or `asya init`):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../base
patches: "${dynamic:patches}"
```

**overlays/\<context\>/kustomization.yaml** (generated by `asya init` or first deploy):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../common
namespace: "${var.namespace}"
```

Platform engineers can add default kustomize features to any layer template:
```yaml
# Platform team adds to overlays template:
commonLabels:
  app.kubernetes.io/managed-by: asya
  asya.sh/flow: "${dynamic:flow}"
```

**Per-context exposure control**: To expose a flow only on stg, add
`configmap-flows.yaml` to base/ (via `asya expose`) and add a `$patch: delete`
in the prod overlay to exclude it:
```yaml
# overlays/prod/remove-expose.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
$patch: delete
```

### 7.3.2 compiler/rules.yaml

Compiler rules are offloaded here when the list grows. For small projects,
rules can also live inline in `config.yaml` under `compiler.rules:` — both
sources merge via list concatenation (`ListMergeMode.EXTEND`).

```yaml
# .asya/compiler/rules.yaml
- match: "tenacity.retry(stop=stop_after_attempt(X))"
  treat-as: config
  assign-to: spec.resiliency.retry.maxAttempts
  where:
    stop:
      stop_after_attempt:
        max_attempt_number: X
  example: "@retry(stop=stop_after_attempt(3))"

- match: "stamina.retry(attempts=X)"
  treat-as: config
  assign-to: spec.resiliency.retry.maxAttempts
  where:
    attempts: X
  example: "@stamina.retry(attempts=5)"

- match: "my_lib.helper"
  treat-as: inline
```

### 7.4 Resolver Syntax

Two families, distinguished by separator:

| Syntax | Source | Resolves when |
|--------|--------|---------------|
| `${var.x}` | Config tree (native OmegaConf) | After merge |
| `${.image}` | Relative sibling key (native OmegaConf) | After merge |
| `${arg:tag}` | CLI `--arg tag=v1` (custom resolver) | At command time |
| `${arg:x,default}` | CLI with fallback (custom resolver) | At command time |
| `${dynamic:actor}` | Compiler-computed (custom resolver) | Per actor, at compile time |
| `${env:HOME}` | Environment variable (custom resolver) | At command time |

**Rule of thumb**: dot = value is in a `.yaml` file. Colon = value is injected
from outside. Missing values are a hard error (no silent fallback).

### 7.5 `${dynamic:*}` Resolver Keys

| Key | Source | Example |
|-----|--------|---------|
| `dynamic:actor` | Actor name, kebab-cased | `"validate-order"` |
| `dynamic:handler` | Fully qualified Python path | `"e_commerce.validate.validate_order"` |
| `dynamic:image` | Resolved OCI image ref | `"ghcr.io/org/e-commerce:${arg:tag}"` |
| `dynamic:flow` | Flow name, kebab-cased | `"order-processing"` |
| `dynamic:flow_role` | Role within flow | `"entrypoint"`, `"router"`, `"processor"` |
| `dynamic:env` | K8s env list (subtree resolver) | `[{name: "ASYA_HANDLER", value: "..."}]` |

These are values the compiler **always** computes per actor. They exist only
in-memory during compilation — no intermediate file.

Resiliency values (`spec.resiliency.retry.*`, `spec.resiliency.timeout`) are
**not** `${dynamic:*}` resolvers — they are placed directly at XR spec paths
via compiler rules (`assign-to: spec.*`). See
`research-compiler-knowledge-base.md`.

`${dynamic:env}` is an OmegaConf subtree resolver that returns a list of K8s
env entries. The compiler constructs this list from:
- `ASYA_HANDLER` (always present)
- `ASYA_HANDLER_*` router mappings (for router actors)
- Env vars detected from handler code (`os.environ`, `os.getenv`)
- Default values extracted from `os.getenv("KEY", "default")`
- Secret refs from `secrets:` section in config.yaml

### 7.6 Key Design Decisions

- **OmegaConf is a real dependency**: Not "inspired by" — the library is used
  directly. OmegaConf handles interpolation (relative refs, lazy resolution),
  custom resolvers (`arg:`, `dynamic:`, `env:`), and merge with
  `ListMergeMode.EXTEND` for list concatenation. Asya adds: walk-up file
  discovery, directory-to-key convention, semantic validation.
- **Directory-to-key convention**: directories under `.asya/` that match a
  root config key have their contents recursively merged. Files become
  sub-keys. Example: `.asya/compiler/rules.yaml` → `compiler.rules`.
  Important scalars stay in `config.yaml`; complex structures offload to
  directories when they grow.
- **Build context follows Python packages, not actors**: Multiple actors can
  share one image if their handlers come from the same package.
- **Build commands are opaque**: Asya is a thin command runner, not a build
  system. `command` is a shell string with variable substitution — any build
  tool works. `asya k build --push` appends a registry push after the build
  command. On-cluster builds (Shipwright) are a separate mechanism, not a
  shell command.
- **Walk-up recursive merge**: Nested `.asya/` directories support monorepos.
  All `.asya/config.yaml` files and content directories merge root-first
  (dicts deep-merge, lists concatenate via `ListMergeMode.EXTEND`).
  Duplicate list entries (same key field, e.g. `module:`) are an error by
  default. A child entry can explicitly replace a parent entry by setting
  `override: true` — without the marker, duplicates are caught at compile time.
- **Three resolver families**: `${var.*}` for config constants (native
  OmegaConf), `${arg:*}` / `${dynamic:*}` / `${env:*}` for external values
  (custom resolvers). Dot = in config, colon = injected.
- **Template vs overlays**: Same as XRD merge — overlays applied first (in
  order, last wins), then template body applies on top. Template values are
  the user's explicit intent and override overlay defaults.
- **Three-layer kustomize**: `base/` (compiler output, regenerated) →
  `common/` (shared user customizations, preserved) → `overlays/<context>/`
  (per-context overrides). `kustomize build overlays/<ctx>/` merges all three
  layers. Docker Compose is generated from effective manifests by `asya d up`.
- **Server-side apply**: `asya k apply` always uses `kubectl apply --server-side`
  with `--field-manager=asya-flow-<name>`. This allows multiple flows to
  contribute data keys to the shared `gateway-flows` ConfigMap without conflicts.
  Since asya fully manages kubectl, mixed apply mode risks don't apply.
- **`project_root: "."`**: Auto-resolved to absolute path at config load time
  (relative to config file's parent directory). OmegaConf has no shell command
  support — `"."` resolution is done by the config loader before merge.

> **Full design**: `research-compiler-resolution.md` (sections 2-3: `.asya/`
> directory, config schema, walk-up merge, variable interpolation, output
> modes, `asya init`).

---

## 8. Three Stages

The lifecycle is three stages: compile, build, apply. No separate render
step — compile stamps AsyncActor XRs directly into kustomize base.

| Stage | CLI | Input | Output |
|-------|-----|-------|--------|
| **Compile** | `asya compile` | source + .asya/*.yaml | routers.py + base/*.yaml (kustomize base) |
| **Build** | `asya k build` | source + build commands | OCI image |
| **Apply** | `asya k apply` | effective manifests (kustomize build) | running pods/containers |

Build defaults to local-only; `--push` adds a registry push.

### 8.1 Three-Layer Kustomize Structure

The manifest directory uses three kustomize layers:

| Layer | Directory | Written by | Lifecycle |
|-------|-----------|-----------|-----------|
| **Base** | `base/` | Compiler (`asya compile`) | Regenerated on every compile |
| **Common** | `common/` | User/UI/CLI (`asya k edit`) | Preserved across recompiles |
| **Overlay** | `overlays/<context>/` | User/platform eng | Per deployment target |

Build chain: `base/ → common/ → overlays/<context>/`. Each layer's
`kustomization.yaml` references the previous as a resource, then adds patches.

**Compile** produces two outputs: router Python code (`routers.py`) and
AsyncActor XR manifests (`base/*.yaml`). Both are read-only and regenerated
on recompile.

**`asya compile flows/order.py`:**
1. Load `.asya/config.yaml` + `.asya/compiler/` → merged OmegaConf config
2. Parse flow AST → extract handler names
3. Apply rules (treat-as classification, config extraction)
4. Group into routers → Router IR
5. For each actor: resolve handler → module → build entry → image,
   set `dynamic:*` values, stamp `compiler.templates.actor` → write to `base/`
6. Stamp layer kustomization templates → write `kustomization.yaml` per layer
7. Generate `routers.py` → write to `compiler.routers` path

**`asya compile --handler e_commerce.validate.validate_order`:**
1. Load `.asya/config.yaml` + `.asya/compiler/` → merged OmegaConf config
2. Resolve handler → module → build entry → image
3. Set `dynamic:*` values, stamp `compiler.templates.actor` → write to `base/`

Same resolution code. Flow compile adds AST parsing + router generation.

**Directory structure** after compile + edit + expose:
```
.asya/manifests/order-processing/
├── base/                              # layer 1: compiler output (regenerated)
│   ├── kustomization.yaml
│   ├── validate-order.yaml
│   ├── express-handler.yaml
│   ├── router-start.yaml
│   ├── end-order-processing.yaml
│   └── configmap-flows.yaml           # gateway exposure (created by asya expose)
├── common/                            # layer 2: shared customizations (preserved)
│   ├── kustomization.yaml             # resources: ../base + patches
│   └── validate-order.yaml            # infra-tier patch (created by asya k edit)
└── overlays/                          # layer 3: per-context
    ├── stg/
    │   └── kustomization.yaml         # resources: ../../common
    └── prod/
        ├── kustomization.yaml         # resources: ../../common
        └── remove-expose.yaml         # $patch: delete to skip exposure on prod
```

**Recompile safety**: `base/` is fully regenerated. `common/` and `overlays/`
are never touched. The `base/kustomization.yaml` resources list is updated to
match `base/`, and existing references in `common/` and overlays are preserved.

**User edits** go into `common/` as kustomize strategic merge patches:
```bash
asya k edit validate-order
# opens $EDITOR on .asya/manifests/order-processing/common/validate-order.yaml
```

When creating a new patch, `asya k edit` pre-populates the file with a
commented template showing common overrides (replicas, resources, env,
resiliency). The user uncomments what they need. Future: the UI and CLI
will provide structured editing commands for these patches.

**Effective manifests** = `kustomize build` on the context overlay:
```bash
asya show order-processing --context stg
# kustomize build .asya/manifests/order-processing/overlays/stg/
```

**List merge behavior**: kustomize strategic merge patches merge `env[]` lists
by the `name` key field — a patch adding `env: [{name: NEW_VAR, value: x}]`
appends rather than replaces. `flavors[]` lists are also merged (appended) at
any layer. To remove a list item, use `$patch: delete`:
```yaml
# common/remove-env.yaml — removes a compiler-generated env var
spec:
  env:
    - name: UNWANTED_VAR
      $patch: delete
```

### 8.1.1 Three-Layer Convention

The three layers map to the XRD v2 two-tier convention (see `xrd-v2/rfc.md`)
plus per-context overrides:

| Layer | Fields | Written by | Purpose |
|---|---|---|---|
| **base/** | `actor`, `image`, `handler`, `env`, `configmap-flows` | Compiler | App tier + gateway exposure |
| **common/** | `flavors`, `scaling`, `resources`, `tolerations`, `resiliency`, `secretRefs` | User/UI/CLI | Infra tier (shared across contexts) |
| **overlays/** | namespace, replicas, exposure control, resource overrides | User/platform eng | Per-context differences |

The compiler owns the app tier in base. The user owns the infra tier in
common. Per-context differences go in overlays. `kustomize build` merges all
three. Recompiling never destroys infrastructure or per-context configuration.

### 8.1.2 Gateway Exposure (`configmap-flows.yaml`)

`asya expose` generates a ConfigMap manifest in `base/configmap-flows.yaml`.
Each flow contributes a single data key to the shared `gateway-flows` ConfigMap:

```yaml
# base/configmap-flows.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gateway-flows
  labels:
    asya.sh/component: gateway
    asya.sh/config-type: flows
data:
  order-processing.yaml: |
    name: order-processing
    entrypoint: start-order-processing
    description: "Process an order end-to-end"
    mcp:
      inputSchema:
        type: object
        properties:
          order_id: { type: string }
        required: [order_id]
```

**Server-side apply with per-flow field managers** prevents conflicts.
`asya k apply` always uses:
```bash
kubectl apply --server-side --field-manager=asya-flow-<flow-name> -f -
```

Each flow's field manager owns only its data key in the ConfigMap. Multiple
flows deploying independently never overwrite each other's keys.

**CLI flags** for `asya expose`:

| Flag | Protocol | Description |
|------|----------|-------------|
| `--description` | shared | Flow description (required) |
| `--timeout` | shared | E2E timeout in seconds |
| `--mcp` | MCP | Enable MCP tool exposure (default if neither --mcp nor --a2a) |
| `--input-schema` | MCP | JSON Schema inline |
| `--input-schema-file` | MCP | JSON Schema from file |
| `--a2a` | A2A | Enable A2A skill exposure |
| `--tags` | A2A | Comma-separated tags |
| `--examples` | A2A | Example prompts (repeatable) |

**Entrypoint auto-detection**: reads compiled manifests in `base/`, finds the
actor with label `asya.sh/flow-role: entrypoint`. No K8s API call needed.

**Per-context control**: `configmap-flows.yaml` is in `base/` (all contexts
see it by default). To exclude on a specific context, add a `$patch: delete`
in that context's overlay (see section 7.3.1).

**Unexpose**: `asya unexpose <flow>` removes `configmap-flows.yaml` from
`base/` and applies a JSON patch to remove the data key from the ConfigMap:
```bash
kubectl patch configmap gateway-flows --type=json \
  -p '[{"op":"remove","path":"/data/order-processing.yaml"}]'
```

See `adr.configmap-flow-registry.md` for the full ConfigMap flow registry
design (schema, RBAC, gateway polling watcher, eventual consistency trade-offs).

### 8.1.3 GitOps and ArgoCD/FluxCD

For GitOps pipelines, the same SSA requirement applies. ArgoCD and FluxCD
must be configured for server-side apply to avoid wiping other flows' ConfigMap
keys:

- **ArgoCD**: `syncOptions: [ServerSideApply=true]` on the Application
- **FluxCD**: `spec.serverSideApply: true` on the Kustomization resource

`asya k apply` on readonly contexts generates manifests but does not apply:
```bash
asya k apply order-processing --context prod
# context "prod" is readonly — commit manifests and apply via GitOps
```

The user commits the three-layer directory to git. The GitOps tool builds
the correct overlay and applies with SSA.

### 8.2 Verbosity Levels

All compile/build/deploy commands are **explicit by default** — showing exactly
what resolved to what. No hidden resolutions.

| Flag | Level | What's shown |
|------|-------|-------------|
| `-q` / `--quiet` | Quiet | No output (exit code only) |
| (default) | Normal | Resolution chain, output files, commands run |
| `-v` / `--verbose` | Verbose | + config merge trace, file paths, interpolation |
| `-vv` | Very verbose | + AST analysis, rule matching, OmegaConf debug |
| `-vvv` | Debug | + full OmegaConf config dump, internal state |

Example (default verbosity):
```
$ asya compile flows/order_processing.py
[compile] Python: /home/user/.venv/bin/python (detected from VIRTUAL_ENV)
[compile] Config: /.asya/config.yaml, /.asya/compiler/ (walk-up)
[compile] Handler: validate_order
           → import: e_commerce.validate.validate_order
           → module: e_commerce → image: ghcr.io/org/e-commerce:${arg:tag}
[compile] Handler: express_handler
           → import: e_commerce.express.express_handler
           → module: e_commerce (same image)
[compile] Routers → ./src/compiled/order-processing/routers.py
[compile] Base → .asya/manifests/order-processing/base/
           → validate-order.yaml
           → express-handler.yaml
           → router-start.yaml
           → end-order-processing.yaml
[compile] Layers → base/kustomization.yaml, common/kustomization.yaml
           → overlays/stg/kustomization.yaml, overlays/prod/kustomization.yaml
```

### 8.3 Error Handling

**Streams**: Normal output (tables, YAML, JSON) goes to stdout. Errors,
progress, and verbose output go to stderr. `-q` suppresses stdout but not
stderr. This enables `asya k status -o json | jq` without error noise.

**Output formats** (`-o` / `--output`):

| Flag | Format | Use case |
|------|--------|----------|
| (default) | Human-readable table | Interactive terminal |
| `-o wide` | Extended table (+ MANIFEST, handler FQN, image) | More detail |
| `-o yaml` | YAML | Piping, scripting |
| `-o json` | JSON | Piping, jq, programmatic access |

**Color**: Error output is colorful (red for `Error:`, yellow for `hint:`,
cyan for file paths). Color is auto-detected via `isatty()` and can be
forced with `--color=always|never|auto` (default: `auto`).

**Error format** (to stderr, colorful):
```
Error: <short description>
  in: <file:line>
  hint: <actionable suggestion>
  config files loaded:
    1. /.asya/config.yaml
    2. /.asya/compiler/rules.yaml
    3. /.asya/compiler/templates/actor.yaml
    4. src/team-a/.asya/config.yaml
```

Every error includes the full list of loaded config files (walk-up merge
chain) so the user can see which files contributed to the effective config,
and points to the specific file:line where the error originates.

**Exit codes**:

| Code | Meaning | When |
|------|---------|------|
| 0 | Success | Command completed |
| 1 | Error | Any failure (config, compile, build, deploy) |
| 2 | Usage error | Wrong arguments, missing required flags |

One exit code for all errors — the error message provides detail. Scripts
check `$?` for pass/fail; humans read the message.

**Error categories**:

| Category | Stage | Examples |
|----------|-------|----------|
| Config | Load | Invalid YAML, unknown keys, duplicate `module:`, unresolved interpolation, missing `.asya/` |
| Compile | Compile | Handler can't be imported, no matching build entry, unsupported AST construct, invalid flow signature |
| Build | Build | Build command exits non-zero (stderr forwarded), image push fails |
| Apply | Apply | Context not configured, readonly violation, kubectl error, unresolved `${arg:*}` in manifest |
| File safety | Any | Target file has uncommitted changes (use `--force` to override) |

**No retry logic.** The CLI fails fast on first error. Retry belongs in CI
pipelines (`retry:` in GitHub Actions, Argo Workflows, etc.), not in the CLI
tool.

**Multi-image builds**: When a flow has multiple unique images, `asya k build`
runs them sequentially with `[build 1/N]` progress prefixes, fail-fast on
first error. Parallel builds deferred until real bottleneck observed.

**Image tags**: No Asya-imposed convention — tagging is a CD concern. Users
provide tags via `--arg tag=<value>`. Recommended: use feature/branch names
(e.g., `--arg tag=add-validation`) to avoid conflicts between developers
sharing a registry.

**Build command errors**: When `command` exits non-zero, Asya forwards the
build tool's stderr verbatim and exits 1:
```
[build] Running: docker build -t ghcr.io/org/e-commerce:v1 .
[build] ...docker output...
Error: build command failed (exit code 1)
  in: /.asya/config.yaml:12 → build[0].command
  hint: check build output above
  config files loaded:
    1. /.asya/config.yaml
```

**Apply errors**: kubectl/docker compose stderr is forwarded verbatim:
```
Error: apply failed
  in: kustomize build .asya/manifests/order-processing/overlays/stg/ | kubectl apply --server-side -f -
  hint: error from server (Forbidden): asyncactors.asya.sh is forbidden
  config files loaded:
    1. /.asya/config.yaml
    2. /.asya/compiler/templates/actor.yaml
```

> **Full design**: `research-compiler-resolution.md` (section 4: stages,
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

Rules are declared in `compiler.rules` (inline in config.yaml or offloaded to
`compiler/rules.yaml`). Most-specific pattern
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

Rules with `where:` trees navigate the Python AST and extract values directly
to AsyncActor XR spec paths (e.g., `spec.resiliency.retry.maxAttempts`).
The compiler uses `inspect.signature` at compile time to resolve parameter
names. Each terminal `assign-to:` has an `example:` field for debugging.

**Hard requirement**: `asya compile` must run in the project's virtualenv with
all decorator/library packages installed (same as mypy/pyright). The compiler
imports library packages referenced in extraction rules to call
`inspect.signature`. User handler code is never imported — only parsed via
`ast.parse`.

Environment variables detected via `os.environ` / `os.getenv` rules are
sourced from the `secrets:` section in `config.yaml`. Default values from
`os.getenv("KEY", "default")` are captured automatically.

### 9.4 Defaults

| Situation | Default | Override |
|-----------|---------|----------|
| Same-package function | `unfold` | Inline comment or rule |
| External function | `inline` | Specific rule |
| Decorator, no rule | Keep at runtime | `treat-as: config` rule |

> **Full design**: `research-compiler-knowledge-base.md` (rules engine,
> `where:`/`assign-to:` tree syntax, env var detection, secrets mapping,
> tenacity/stamina signatures). Compiler rule CLI is deferred — users edit
> `.asya/compiler/rules.yaml` directly.
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

One actor belongs to at most one flow. If the same handler is used in multiple
flows, each flow gets its own actor (same handler, flow-scoped name, independent
queue and scaling).

**Naming convention**: Actors compiled within flow `foo-bar` are postfixed with
the flow name: `validate-order-foo-bar`. Standalone actors (deployed outside a
flow) keep their original name: `validate-order`.

**Compile-time collision detection**: The compiler scans
`.asya/manifests/*/base/*.yaml` — all locally-compiled flows, not just the
current one. If `validate-order-foo-bar` already exists in another flow's
manifests, the compiler appends a numeric suffix: `validate-order-foo-bar-1`.
Local directory scan, no cluster access needed.

**Apply-time collision protection**: No pre-check needed — SSA handles this
natively. Each flow applies with `--field-manager=asya-flow-<name>`. If two
flows produce the same actor name, the second apply fails with an SSA field
ownership conflict (both managers claim `spec.*`, `metadata.labels`, etc.).
The CLI catches the SSA conflict error and produces a friendly message:
*"Actor 'validate-order-foo-bar' already exists and is owned by flow 'baz'."*

This also protects against collisions with standalone actors — client-side
`kubectl apply` uses its own field manager, so SSA conflicts naturally. Zero
overhead: no extra API calls, just error handling on the apply that was going
to happen anyway.

### 10.2 What `asya k apply` Does

For K8s contexts:
1. Selects overlay for the active context (`overlays/<context>/`)
2. Runs `kustomize build` on the overlay (merges base → common → overlay)
3. Pipes effective manifests to `kubectl apply --server-side --field-manager=asya-flow-<name> -f -`
4. Prints each command before execution (`+` prefix, like `set -x`)

For GitOps (readonly contexts):
1. `asya show <flow>` prints effective manifests to stdout
2. User commits manifests directory (base + common + overlays) to git
3. FluxCD/ArgoCD picks up and applies with SSA (must be configured, see 8.1.3)

Local Docker testing is handled separately by `asya d up` (see section 12).

### 10.3 Rollback (Deferred)

No `asya k rollback` command in v0. Three rollback paths exist without it:

| Path | Command | When |
|------|---------|------|
| K8s native | `kubectl rollout undo deployment/<actor>` | Quick undo of last pod change |
| Git + apply | `git revert <commit>` then `asya k apply` | Manifest-level rollback |
| GitOps | Revert PR in CI/CD | Production (readonly contexts) |

A dedicated rollback command is deferred — it requires defining "previous
version" semantics (git history? internal version log?) which is tightly
coupled to the git/GitOps strategy (see §12.2).

### 10.4 Router Actors

Routers are lightweight (pure Python routing logic). They use the
`${var.router_image}` base image with code injected via ConfigMap. No custom
build needed. Platform engineers define a `flow-router` flavor for minimal
resources.

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
asya compile flows/order.py
asya k edit validate-order             # add scaling patch in common/
asya expose order-processing --description "Process orders" --input-schema-file schema.json
asya k build order-processing --arg tag=v1
asya k apply order-processing --context stg
# + kustomize build .asya/manifests/order-processing/overlays/stg/
# + kubectl apply --server-side --field-manager=asya-flow-order-processing -f -
```

**Local testing (Docker Compose)**:
```
asya d up flows/order.py
# compiles flow, generates docker-compose.yaml with sidecar + socket transport, starts containers
```

**Production (GitOps)**: Declarative, reviewed, git-driven.
```
git add .asya/manifests/order-processing/
git commit -m "promote order-processing to prod"
git push  # ArgoCD/Flux watches overlays/prod/
```

### 12.2 Promotion (deferred)

`asya promote` is deferred. The promotion workflow (image pinning, lock file
verification, PR creation) is tightly coupled to git/GitOps CI/CD strategy
and needs design once the base compile/build/deploy flow is validated.

For now, users commit `.asya/manifests/` to git manually. The three-layer
kustomize structure already supports this: `base/` has compiler output,
`common/` has user patches, `overlays/prod/` has production overrides.
ArgoCD/Flux runs `kustomize build overlays/prod/` from the committed directory.

See `research-seamless-build.md` §4 for promotion strategy research
(lock file model, three strategies, CI behavior) — to be revisited when
designing `asya promote`.

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

%asya compile order_processing
%asya k status order-processing
%asya k call analyze '{"text": "hello world"}'
%asya k stream <task-id>
```

### 15.3 Visualization

**Two tiers**: static files for sharing, interactive widgets for live work.

**Static output** (`--plot`):
```python
%asya compile order_processing --plot                # DOT + PNG (default)
%asya compile order_processing --plot --format svg   # DOT + SVG
```
Saves to `.asya/flows/plots/<flow>/` (configurable via `config.plots.dir`).
Same behavior in CLI and Jupyter — deterministic files, no JS dependency.
Formats: `png` (default), `svg`, `dot`.

**Interactive widget** (default in Jupyter):
```python
%asya compile order_processing   # → anywidget inline (no --plot needed)
%asya k status order-processing  # → live status widget
```
In Jupyter, `%asya compile` renders an interactive graph inline via anywidget.
Nodes are actors/routers, edges are message routes. Clicking a node reveals
configuration, live logs, and queue depth. The widget uses `@asya/ui` React
components — the same components rendered in VSCode, standalone web, and Jupyter.

### 15.4 `@asya/ui` React Component Reuse

`@asya/ui` is a host-agnostic React component library. Components receive data
via props and emit events via callbacks. Each surface provides the data bridge:

| Surface | Host mechanism | Data bridge |
|---|---|---|
| Jupyter | anywidget | Python model ↔ widget state ↔ React props |
| VSCode extension | webview panel | Extension host ↔ `postMessage` ↔ React props |
| `asya serve` | standalone web | HTTP/WebSocket ↔ React state ↔ React props |

The components don't know where they're running. anywidget wraps them as
ipywidgets for Jupyter; VSCode renders them in webview iframes; the standalone
web app mounts them directly.

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

- `asya mcp *` commands continue to work (moved under `asya k call`)
- `asya compile` replaces `asya flow compile` / `asya flow validate`
- Only the package name changes (`asya-cli` -> `asya-lab`)

---

## 18. Phasing

### Phase 1: Core SDK + CLI restructure
- Package creation, migration from asya-cli
- SDK extraction (compiler, MCP client)
- `.asya/` config schema (config.yaml + compiler/ directory),
  directory-to-key merge, walk-up merge, `asya init`
- Three-layer kustomize compile (base/ + common/ + overlays/)
- `asya k edit` (create/open patches in common/)
- `asya show` (kustomize build overlay → effective manifests)
- `asya compile`, `asya k status/logs/apply` (with SSA)

### Phase 2: Build + deploy + testing
- `asya k build` (opaque command, `--push` for registry)
- `asya k apply/delete` for K8s (kustomize build | kubectl apply --server-side)
- `asya expose/unexpose` (configmap-flows.yaml generation + SSA apply)
- `asya d up` (compile + generate docker-compose.yaml + start containers)
- `actor-image.lock` (deferred: `asya promote` designed later with GitOps/CI)
- `asya_lab.testing` pytest fixtures

### Phase 3: Message operations + Jupyter
- `where:`/`assign-to:` extraction with full rule set [1fmi]
- Compiler rule CLI (deferred from Phase 1 — users edit config directly)
- `asya k secret create/remove/list/show`
- `asya k send/trace` (queue), `asya d send/trace` (socket)
- Jupyter magics, interactive flow visualization

### Phase 4: Server + advanced features
- `asya serve` local HTTP/WS server
- Protocol-agnostic `asya k call` (MCP + A2A)

---

## 19. Related Epics

| Epic | Relationship |
|---|---|
| 1jow (Client UX Design) | Parent design |
| 1jpc (Client CLI) | Superseded by this RFC |
| 1juv (Asya UI) | `@asya/ui` bundle goes into `[ui]` extra |
| 1juy (Asya Lens) | Docker image that packages `asya-lab[ui,deploy]` |
| 1is3 (GitOps Flow Design) | Informs apply/delete semantics |
| 1g2t (Gateway Dynamic Tool Exposure) | Powers `asya expose` |
| 1iu4 (Local Testing Workflow) | Informs Docker Compose context |

---

## 20. Research Documents

Detailed designs that inform this RFC:

| Document | Covers |
|---|---|
| `research-compiler-resolution.md` | `.asya/` directory, config schema (three files), walk-up merge, OmegaConf resolvers, stages, Python resolution |
| `research-compiler-knowledge-base.md` | Compiler rules engine, `treat-as` values, pattern matching, config extraction, tenacity/stamina signatures |
| `research-no-dockerfile.md` | Build strategies (apko, buildpacks, Cog, Wolfi/distroless), comparison matrix, golden paths |
| `research-seamless-build.md` | Build execution (local, Shipwright, CI), promotion strategies, `actor-image.lock`, two user flows |
| `artem-research-compiler-resolution.md` | Stages overview, compile-time resolution chain, `asya.yaml` role |
| `adr.no-cog.md` | Cog as supported GPU build path (revised) |
| `adr.compiler-template-not-helm.md` | Output template uses OmegaConf resolvers, not Helm |
| `xrd-v2/rfc.md` | Flat AsyncActor XRD v1alpha2 spec, two-tier convention, flavor overlap rules |
| `adr.kustomize-not-extra-dependency.md` | Kustomize bundled with kubectl, no extra binary needed |
| `a2a-protocol-compliance-gateway/adr.configmap-flow-registry.md` | ConfigMap-based flow registry, gateway polling, RBAC, SSA field managers |
| `../asya-ui/rfc.md` | `@asya/ui` React component library, React Flow graph, provider pattern, anywidget/VSCode/web integration (moved from `research-ui-components.md`) |

---

## 21. Open Questions

1. **Click vs argparse**: Current CLI uses argparse. Should the new CLI use
   Click?

2. ~~**Jupyter widget framework**~~: **Resolved**. Two tiers: static files
   (DOT + PNG/SVG via `--plot --format`) for sharing, anywidget + `@asya/ui`
   React components for interactive Jupyter widgets. No JupyterLab extension
   needed — anywidget works in JupyterLab, classic Notebook v7, VS Code
   notebooks, and Colab. Same React components reused in VSCode webview panels
   and `asya serve`. See §15.3–15.4.

3. ~~**Docker Compose generation**~~: **Resolved**. Docker Compose now uses
   sidecar + socket transport (same architecture as K8s, no orchestrator).
   `asya d up` compiles, generates compose, and starts containers in one
   command. See `adr.k-d-command-split.md` for the `asya k` / `asya d`
   command split decision.

4. **Non-Python actors**: The `module:` field is Python-specific. Go actors,
   shell scripts, or pre-built images need a different matching strategy.

5. ~~**`${arg:tag}` lifecycle per output mode**~~: **Resolved**. Pass-through
   resolver: compile defers `${arg:*}` if not provided (literal pass-through),
   deploy/build fail-fast if unresolved. For GitOps, pass `--arg` at compile
   time. See `research-compiler-resolution.md` section 3.4.

6. **Lock file vs opaque builds**: Opaque build commands limit `actor-image.lock`
   to tracking final image digest, not input reproducibility. Acceptable for v1;
   structured `build.intent:` can be added later without schema break.

7. ~~**Kustomize as hard dependency**~~: **Resolved**. Kustomize is bundled with
   kubectl since v1.14 — `kubectl apply -k` does `kustomize build` + `apply`.
   No extra binary. Users without patches can still `kubectl apply -f base/`.
   Helm output backend deferred to future iteration. See
   `adr.kustomize-not-extra-dependency.md`.

8. **Socket transport for Docker Compose**: The `asya d` commands rely on a
   socket transport in the sidecar for local Docker Compose runs (no message
   queue). This transport is not yet implemented and is a dependency for the
   `asya d up` workflow.

See also open questions in `research-compiler-resolution.md` (section 8) and
`research-seamless-build.md` (section 8).
