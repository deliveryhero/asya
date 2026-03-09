# RFC: Asya Lab -- Python SDK, CLI, and Jupyter Magics

**Status**: Proposed (revised 2026-03-09)
**Date**: 2026-02-27 (original), 2026-03-08 (revised), 2026-03-09 (kustomize-native)
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
asya flow compile <flow.py>          # Python -> base/*.yaml + routers.py (kustomize base)
asya flow edit <actor>               # open kustomize patch for actor (create if needed)
asya flow show <flow>                # print effective manifests (kustomize build)
asya flow compose <flow>             # generate docker-compose.yaml from effective manifests
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
asya actor compile --handler <fqn>   # generate compiled manifest for standalone actor
asya actor edit <actor>              # open kustomize patch for actor
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

### 5.4 Compiler Rules

```bash
asya compiler-rule add \             # add extraction rule
  "tenacity.retry(stop=stop_after_attempt(X))" \
  --assign-to spec.resiliency.retry.maxAttempts
asya compiler-rule add "my_lib.helper" --treat-as inline  # classification
asya compiler-rule list              # list all rules (built-in + project)
asya compiler-rule remove <match>    # remove a rule
asya compiler-rule explain <match>   # show what compiler does with a symbol
```

Pattern uses Python-like syntax with `X` as the capture marker. The CLI
parses the expression, builds a `where:` tree, and auto-generates `example:`.
See `research-compiler-knowledge-base.md` for full syntax.

### 5.5 Secret Mapping

```bash
asya secret create <VAR> --secret <name> --key <key>  # register mapping
asya secret remove <VAR>                               # remove mapping
asya secret list                                       # list all mappings
```

Manages the `secrets:` section in `config.yaml`. Actual K8s Secrets are
managed separately (kubectl, Vault, ExternalSecrets).

### 5.6 File Safety

All commands that generate or modify files refuse to overwrite unless the
target is git-committed. Prevents accidental loss of manual edits.

- `asya flow compile` → won't overwrite dirty routers.py or base/ manifests
- `asya flow compose` → won't overwrite dirty docker-compose.yaml
- `asya compiler-rule add` → won't overwrite dirty compiler/rules.yaml
- `asya secret create` → won't overwrite dirty config.yaml
- Override with `--force`

All file-generating commands show the git diff of their changes.

### 5.7 Command Transparency

All CLI commands that execute external tools print what they run, like
`set -x` in shell. Commands are printed to stderr before execution:

```
$ asya flow deploy order-processing --context=k8s-stg
+ kustomize build .asya/manifests/order-processing/
+ kubectl apply -f - --context=stg-cluster -n e-commerce-stg
asyncactor.asya.sh/validate-order configured
asyncactor.asya.sh/router-start-order-processing configured

$ asya flow compose order-processing
+ kustomize build .asya/manifests/order-processing/
[compose] Translating 4 AsyncActor XRs → .asya/compose/order-processing.yaml
[compose] Wrote .asya/compose/order-processing.yaml

$ asya flow deploy order-processing --context=local
+ docker compose -f .asya/compose/order-processing.yaml up -d
```

This makes every CLI action auditable and reproducible — the user can
copy-paste the printed commands to run them manually.

### 5.7 Project / Infrastructure

```bash
asya init                            # scaffold .asya/ via Copier (full template, works immediately)
asya init --template minimal         # + simple flow with two actors
asya init --template agentic-full    # + full agentic flow example
asya serve                           # start local HTTP/WS server for UI
asya context list                    # list contexts
asya context use <name>              # switch context
# asya <actor/flow> promote                 # promote staging image to prod PR -> UNDEFINED, needs more design
```

`asya init` uses [Copier](https://copier.readthedocs.io/) for scaffolding.
Generates `compiler/templates/actor.yaml` (AsyncActor CRD with `${dynamic:*}`
holes) so compile works out of the box. `--template` adds sample flows and
actors (minimal, full, agentic-minimal, agentic-full). Contexts section is
commented out — configured when ready to deploy. See
`research-compiler-resolution.md` section 2.4.

### 5.9 Command Data Sources

No CLI command uses the gateway's internal `/mesh/*` routes -- those are
reserved for sidecar-to-gateway communication.

| Command | Backend | Protocol / API |
|---------|---------|---------------|
| `asya flow call <flow>` | Gateway | MCP `tools/call` or A2A `message/send` |
| `asya flow stream <id>` | Gateway | MCP streamable HTTP or A2A subscribe |
| `asya flow list` | Local + context | Decorator scan + manifests + K8s/Docker |
| `asya actor list` | Local + context | Manifests + K8s/Docker |
| `asya flow show <flow>` | Local | `kustomize build` → effective manifests |
| `asya flow compose <flow>` | Local | Effective manifests → docker-compose.yaml |
| `asya flow status <flow>` | Context | `kubectl get` or `docker compose ps` |
| `asya flow logs <flow>` | Context | `kubectl logs` or `docker compose logs` |
| `asya flow deploy/undeploy` | Context | `kubectl apply/delete` or `docker compose up/down` |
| `asya flow edit <actor>` | Local | Opens/creates kustomize patch file |
| `asya actor compile` | Local | Config + Python resolution (no K8s needed) |
| `asya actor build` | Build tool | Opaque shell command from config.yaml |
| `asya compiler-rule *` | Local | Reads/writes compiler/rules.yaml |
| `asya secret *` | Local | Reads/writes config.yaml secrets: |
| `asya context *` | Local | Reads/writes config.yaml contexts: / default_context: |
| `asya msg send <target>` | MQ | Direct queue publish (SQS/RabbitMQ API) |
| `asya msg trace <id>` | Observability | OpenTelemetry trace query |

### 5.10 List Commands (Discovery)

`asya flow list` and `asya actor list` show a unified outer-join table across
three data sources: local source files, compiled manifests, and deployed state
in the current context.

**Flow discovery**: Scan all `.py` files under `var.project_root` for `@actor`
and `@flow` decorators. Decorator names are matched against compiler rules
(`treat-as: actor`, `treat-as: flow`). Later: a shipped `asya` Python package
will provide pre-built decorators.

**Data sources** (joined by name):

| Column | Source | Available when |
|--------|--------|----------------|
| SOURCE | `.py` files with `@flow`/`@actor` decorators | Always (pre-compile) |
| COMPILED | `.asya/manifests/<flow>/` YAML files | After `asya flow compile` |
| DEPLOYED | K8s `asyncactor` resources or Docker containers | After `asya deploy` |

**Default output** (`asya flow list`):
```
FLOW               SOURCE            NUM_ACTORS    NUM_ROUTERS   DEPLOYED (k8s-stg)
order-processing   flows/order.py    3             8             11/11 Running
image-pipeline     flows/image.py    2             5             —
new-experiment     flows/exp.py      —             —             —
legacy-flow        —                 —             —             2/2 Running
```

**Default output** (`asya actor list`):
```
ACTOR              SOURCE              FLOW               DEPLOYED (k8s-stg)
validate-order     path/actor1.py      order-processing   1/1 Running
express-handler    path/actor2.py      order-processing   0/0 Napping
router-start       path/actor3.py      order-processing   1/1 Running
old-actor          path/actor4.py      —                  1/1 Running
```

**Wide output** (`-o wide`) adds MANIFEST column (full path to manifest file)
and additional detail (handler FQN, image ref).

**Deployed column** queries the current context — K8s (kubeconfig) or Docker
(local compose). Rows with no local source/manifest but deployed = managed
outside Asya.

### 5.11 Protocol Handling

`asya flow call` and `asya flow expose` accept a `--protocol=mcp|a2a` flag.
Default is configurable. DS should not need to care about MCP vs A2A.

### 5.12 Log Display

`asya flow logs <flow>` aggregates logs from all actors in the flow, prefixed
with a colored actor name (like `docker compose logs`).

### 5.13 Deploy/Undeploy Semantics

Behavior depends on active context type:

| Context type | `deploy` | `undeploy` |
|---|---|---|
| `kubernetes` | `kustomize build \| kubectl apply -f -` | `kubectl delete` manifests |
| `docker` | `docker compose -f <compose_file> up -d` | `docker compose down` |

**K8s deploy**: runs `kustomize build` on the flow's manifest directory
(merges base + patches), pipes effective manifests to `kubectl apply`.

**Docker deploy**: requires a compose file generated by `asya flow compose`.
If missing, errors with hint to run `asya flow compose <flow>` first.

K8s safety rule: `asya flow deploy` checks for existing deployment. If a
different version exists, errors and asks to undeploy first. Identical version
exits 0 (idempotent).

---

## 6. Context System

A context is a named profile that bundles everything needed to reach a
deployment target: cluster, namespace, gateway URL, and permissions.

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
    readonly: true                  # blocks deploy/undeploy, allows status/logs/call
  local:
    type: docker
    gateway: http://localhost:8080  # optional, if gateway runs in compose

default_context: stg
```

### 6.2 Context Types

| Type | `deploy`/`undeploy` | `status` | `logs` | `list` DEPLOYED | `call`/`stream` |
|------|---------------------|----------|--------|-----------------|-----------------|
| `kubernetes` | `kubectl apply/delete` | `kubectl get asyncactor` | `kubectl logs -l` | `kubectl get asyncactor` | Gateway URL |
| `docker` | `docker compose up/down` | `docker compose ps` | `docker compose logs` | `docker compose ps` | Gateway URL |

**`kubernetes`** fields:
- `kubecontext` (required): kubeconfig context name
- `namespace` (required): K8s namespace
- `gateway` (optional): gateway URL for `call`/`stream`
- `readonly` (optional, default `false`): blocks deploy/undeploy/promote

**`docker`** fields:
- `compose_output` (optional, default `.asya/compose/`): directory for
  generated compose files
- `gateway` (optional): gateway URL, typically `http://localhost:<port>`

**Docker Compose generation** (`asya flow compose`):

Docker Compose files are generated **explicitly** by `asya flow compose`, not
implicitly at deploy time. The command translates effective K8s manifests
(kustomize build output) into a compose file:

```bash
asya flow compose order-processing
# + kustomize build .asya/manifests/order-processing/
# [compose] Translating 4 AsyncActor XRs → .asya/compose/order-processing.yaml
# [compose] Wrote .asya/compose/order-processing.yaml
```

The compose file is saved to disk (path configurable via
`contexts.<name>.compose_output`) and committed to git like any other artifact.

**Docker Compose architecture** (no sidecar, no message queue):

```
┌─────────────┐     unix socket     ┌──────────────────┐
│ Orchestrator │ ──────────────────→ │ Actor A runtime  │
│  (Python)    │ ←────────────────── │ (user image)     │
│              │     unix socket     ├──────────────────┤
│  reads flow  │ ──────────────────→ │ Actor B runtime  │
│  topology    │ ←────────────────── │ (user image)     │
│              │         ...         ├──────────────────┤
│  routes msgs │ ──────────────────→ │ Router runtime   │
│  sequentially│ ←────────────────── │ (router image)   │
└─────────────┘                     └──────────────────┘
```

- **No sidecar**: orchestrator calls runtimes directly via HTTP-over-Unix-socket
- **No message queue**: synchronous routing through the flow's route chain
- **One runtime container per actor**: same image as K8s, same handler
- **One orchestrator container**: uses `asya-testing` package (same code
  that drives integration tests), reads compiled flow topology, exposes
  HTTP endpoint for `asya flow call`

**Translation rules** from AsyncActor XR to Docker Compose service:

| XR field | Compose equivalent |
|---|---|
| `metadata.name` | Service name |
| `spec.image` | `image:` |
| `spec.handler` | `ASYA_HANDLER` env var |
| `spec.actor` | `ASYA_ACTOR_NAME` env var |
| `spec.env[]` | `environment:` |
| `spec.resiliency` | Orchestrator retry config |
| `spec.transport` | Ignored (no queue locally) |
| `spec.scaling` | Ignored (no autoscaling locally) |
| `spec.flavors` | Ignored (K8s-only) |
| `spec.tolerations` | Ignored (K8s-only) |
| `spec.nodeSelector` | Ignored (K8s-only) |
| `spec.secretRefs` | Ignored (use `.env` file locally) |

Generated compose file:
```yaml
# .asya/compose/order-processing.yaml (generated by asya flow compose)
services:
  orchestrator:
    image: ghcr.io/asya-sh/asya-testing:latest
    volumes:
      - actor-sockets:/var/run/asya
    ports: ["8080:8080"]

  validate-order:
    image: ghcr.io/org/e-commerce:latest
    command: python /opt/asya/asya_runtime.py
    environment:
      ASYA_HANDLER: e_commerce.validate.validate_order
      ASYA_ACTOR_NAME: validate-order
    volumes:
      - actor-sockets:/var/run/asya

  router-start-order-processing:
    image: ghcr.io/asya-sh/asya-runtime:latest
    command: python /opt/asya/asya_runtime.py
    environment:
      ASYA_HANDLER: compiled.order_processing.routers.start_order_processing
      ASYA_ACTOR_NAME: router-start-order-processing
      ASYA_HANDLER_VALIDATE_ORDER: e_commerce.validate.validate_order
      ASYA_HANDLER_EXPRESS_HANDLER: e_commerce.express.express_handler
    volumes:
      - actor-sockets:/var/run/asya

volumes:
  actor-sockets:
```

The orchestrator is implemented in `asya-testing` — the same package that
drives integration tests. It replaces sidecar + transport for local
development. From the handler's perspective, the runtime environment is
identical (same Unix socket protocol, same handler interface).

### 6.3 Resolution Order

Highest priority first:

1. `--context` flag on the command
2. `ASYA_CONTEXT` environment variable
3. `default_context` field in config.yaml

**No auto-detection fallback.** If no context is resolved, commands that need
a deployment target fail with:
```
Error: no context configured
  hint: add contexts: section to .asya/config.yaml
  hint: or pass --context=<name>
  see: asya init --help
```

Commands that don't need a context (compile, build, compiler-rule, secret)
work without one.

### 6.4 CLI

```bash
asya context list                  # show all contexts, mark active
asya context use <name>            # set default_context in config.yaml
```

`asya context list` output:
```
  NAME    TYPE         NAMESPACE    GATEWAY                      READONLY
* stg     kubernetes   team-one     https://gw.stg.internal      no
  prod    kubernetes   prod         https://gw.prod.internal     yes
  local   docker       —            http://localhost:8080         no
```

`asya context use prod` writes `default_context: prod` to config.yaml.
Committed to git = team-shared default. Per-developer override via
`ASYA_CONTEXT` env var.

### 6.5 Read-Only Enforcement

Contexts with `readonly: true` block write operations:
- `asya flow deploy/undeploy` → error
- `asya actor deploy/undeploy` → error
- `asya promote` → error (production writes happen via GitOps PR)

Read operations always allowed: `status`, `logs`, `list`, `call`, `stream`.

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
│       ├── kustomization.yaml   # auto-maintained by CLI
│       ├── base/                # compiler output (regenerated)
│       └── patches/             # user/UI edits (preserved)
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
    command:
      local: "docker build -t ${..image} ."
      remote: "${.local} && docker push ${..image}"

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
readable and directly maps to what `asya flow edit` exposes.

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

### 7.3.1 compiler/templates/kustomization.yaml

Template for the auto-generated `kustomization.yaml` in each flow's manifest
directory. The compiler stamps this once per flow, then updates `resources:`
and `patches:` lists on subsequent compiles/edits.

```yaml
# .asya/compiler/templates/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources: "${dynamic:resources}"
patches: "${dynamic:patches}"
```

Platform engineers can add default kustomize features:
```yaml
# Platform team adds:
namespace: "${var.namespace}"
commonLabels:
  app.kubernetes.io/managed-by: asya
  asya.sh/flow: "${dynamic:flow}"
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
| `${..image}` | Relative parent key (native OmegaConf) | After merge |
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
  system. `command.local` and `command.remote` are shell strings with variable
  substitution. Any build tool works.
- **Walk-up recursive merge**: Nested `.asya/` directories support monorepos.
  All `.asya/config.yaml` files and content directories merge root-first
  (dicts deep-merge, lists concatenate via `ListMergeMode.EXTEND`).
- **Three resolver families**: `${var.*}` for config constants (native
  OmegaConf), `${arg:*}` / `${dynamic:*}` / `${env:*}` for external values
  (custom resolvers). Dot = in config, colon = injected.
- **Template vs overlays**: Same as XRD merge — overlays applied first (in
  order, last wins), then template body applies on top. Template values are
  the user's explicit intent and override overlay defaults.
- **Kustomize-native**: Compile stamps XRs directly into `base/`. No render
  step, no helm values, no abstract IR. User edits go into kustomize patches.
  `kustomize build` merges base + patches → effective manifests. Docker Compose
  is generated explicitly from effective manifests (`asya flow compose`).
- **`project_root: "."`**: Auto-resolved to absolute path at config load time
  (relative to config file's parent directory). OmegaConf has no shell command
  support — `"."` resolution is done by the config loader before merge.

> **Full design**: `research-compiler-resolution.md` (sections 2-3: `.asya/`
> directory, config schema, walk-up merge, variable interpolation, output
> modes, `asya init`).

---

## 8. Three Stages

The lifecycle is three stages: compile, build, deploy. No separate render
step — compile stamps AsyncActor XRs directly into kustomize base.

| Stage | CLI | Input | Output |
|-------|-----|-------|--------|
| **Compile** | `asya [flow\|actor] compile` | source + .asya/*.yaml | routers.py + base/*.yaml (kustomize base) |
| **Build** | `asya [flow\|actor] build` | source + build commands | OCI image |
| **Deploy** | `asya [flow\|actor] deploy` | effective manifests (kustomize build) | running pods/containers |

Build and deploy use `--local`/`--remote` flags for execution context.

### 8.1 Kustomize-Native Compilation

**Compile** produces two outputs: router Python code (`routers.py`) and
AsyncActor XR manifests (`base/*.yaml`). Both are read-only and regenerated
on recompile.

**`asya flow compile flows/order.py`:**
1. Load `.asya/config.yaml` + `.asya/compiler/` → merged OmegaConf config
2. Parse flow AST → extract handler names
3. Apply rules (treat-as classification, config extraction)
4. Group into routers → Router IR
5. For each actor: resolve handler → module → build entry → image,
   set `dynamic:*` values, stamp `compiler.templates.actor` → write to `base/`
6. Stamp `compiler.templates.kustomization` → write `kustomization.yaml`
7. Generate `routers.py` → write to `compiler.routers` path

**`asya actor compile --handler e_commerce.validate.validate_order`:**
1. Load `.asya/config.yaml` + `.asya/compiler/` → merged OmegaConf config
2. Resolve handler → module → build entry → image
3. Set `dynamic:*` values, stamp `compiler.templates.actor` → write to `base/`

Same resolution code. Flow compile adds AST parsing + router generation.

**Directory structure** after compile:
```
.asya/manifests/order-processing/
├── kustomization.yaml              # auto-generated, references base + patches
├── base/                           # compiler output (regenerated on recompile)
│   ├── validate-order.yaml
│   ├── express-handler.yaml
│   ├── router-start.yaml
│   └── end-order-processing.yaml
└── patches/                        # user/UI edits (preserved across recompiles)
    └── validate-order.yaml         # created by `asya flow edit validate-order`
```

**Recompile safety**: `base/` is fully regenerated. `patches/` is never
touched. The `kustomization.yaml` resources list is updated to match
`base/`, and existing patch references are preserved.

**User edits** go into kustomize strategic merge patches:
```bash
asya flow edit validate-order
# opens $EDITOR on .asya/manifests/order-processing/patches/validate-order.yaml
```

**Effective manifests** = `kustomize build .asya/manifests/order-processing/`:
```bash
asya flow show order-processing    # prints effective manifests to stdout
```

**List merge behavior**: kustomize strategic merge patches merge `env[]` lists
by the `name` key field — a patch adding `env: [{name: NEW_VAR, value: x}]`
appends rather than replaces. `flavors[]` lists are also merged (appended) at
any overlay level.

### 8.1.1 Two-Tier Convention

The compile output and user patches naturally map to the XRD v2 two-tier
convention (see `xrd-v2/rfc.md`):

| Tier | Fields | Written by | Kustomize layer |
|---|---|---|---|
| **App tier** | `actor`, `image`, `handler`, `env` | Compiler | `base/` |
| **Infra tier** | `flavors`, `scaling`, `resources`, `tolerations`, `resiliency`, `secretRefs` | User/UI/CLI | `patches/` |

The compiler owns the app tier in base. The user owns the infra tier in
patches. `kustomize build` merges them. This separation means recompiling
never destroys infrastructure configuration.

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
$ asya flow compile flows/order_processing.py
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
[compile] Kustomization → .asya/manifests/order-processing/kustomization.yaml
```

### 8.3 Error Handling

**Streams**: Normal output (tables, YAML, JSON) goes to stdout. Errors,
progress, and verbose output go to stderr. `-q` suppresses stdout but not
stderr. This enables `asya actor list -o json | jq` without error noise.

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
| Deploy | Deploy | Context not configured, readonly violation, kubectl error, unresolved `${arg:*}` in manifest |
| File safety | Any | Target file has uncommitted changes (use `--force` to override) |

**No retry logic.** The CLI fails fast on first error. Retry belongs in CI
pipelines (`retry:` in GitHub Actions, Argo Workflows, etc.), not in the CLI
tool.

**Build command errors**: When `command.local` or `command.remote` exits
non-zero, Asya forwards the build tool's stderr verbatim and exits 1:
```
[build] Running: docker build -t ghcr.io/org/e-commerce:v1 .
[build] ...docker output...
Error: build command failed (exit code 1)
  in: /.asya/config.yaml:12 → build[0].command.local
  hint: check build output above
  config files loaded:
    1. /.asya/config.yaml
```

**Deploy errors**: kubectl/docker compose stderr is forwarded verbatim:
```
Error: deploy failed
  in: kustomize build .asya/manifests/order-processing/ | kubectl apply -f -
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
> `asya compiler-rule` CLI, tenacity/stamina signatures).
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

For K8s contexts:
1. Runs `kustomize build` on the flow's manifest directory (base + patches)
2. Pipes effective manifests to `kubectl apply -f -`
3. Prints each command before execution (`+` prefix, like `set -x`)

For Docker contexts:
1. Requires compose file generated by `asya flow compose` (errors if missing)
2. Runs `docker compose -f <compose_file> up -d`

For GitOps:
1. `asya flow show <flow>` prints effective manifests to stdout
2. User commits manifests directory (base + patches) to git
3. FluxCD/ArgoCD picks up and applies

### 10.3 Router Actors

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
asya flow compile flows/order.py
asya flow edit validate-order          # add scaling patch
asya flow build order-processing --local --arg tag=v1
asya flow deploy order-processing --context=k8s-stg
# + kustomize build .asya/manifests/order-processing/
# + kubectl apply -f - --context=stg-cluster -n team-one
```

**Local testing (Docker Compose)**:
```
asya flow compile flows/order.py
asya flow compose order-processing     # explicit: save docker-compose.yaml
# + kustomize build .asya/manifests/order-processing/
# [compose] Wrote .asya/compose/order-processing.yaml
asya flow deploy order-processing --context=local
# + docker compose -f .asya/compose/order-processing.yaml up -d
```

**Production (GitOps)**: Declarative, reviewed, git-driven.
```
asya promote my-actor --context=k8s-prod
# -> verifies actor-image.lock, creates PR with source + lock + manifests
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
- `.asya/` config schema (config.yaml + compiler/ directory),
  directory-to-key merge, walk-up merge, `asya init`
- Kustomize-native compile (base/*.yaml + kustomization.yaml generation)
- `asya flow edit` (create/open kustomize patches)
- `asya flow show` (kustomize build → effective manifests)
- Flow and actor commands (list, status, logs, compile)

### Phase 2: Build + deploy + testing
- `asya [flow|actor] build` (opaque commands, `--local`/`--remote`)
- `asya [flow|actor] deploy/undeploy` for K8s (kustomize build | kubectl apply)
- `asya flow compose` (effective manifests → docker-compose.yaml)
- `asya [flow|actor] deploy/undeploy` for Docker Compose
- `actor-image.lock` and `asya promote`
- `asya_lab.testing` pytest fixtures

### Phase 3: Message operations + Jupyter
- `where:`/`assign-to:` extraction with full rule set [1fmi]
- `asya compiler-rule add/remove/list/explain`
- `asya secret create/remove/list`
- `asya msg send/trace/replay/inspect/drain`
- Jupyter magics, interactive flow visualization

### Phase 4: Server + advanced features
- `asya serve` local HTTP/WS server
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
| `research-compiler-resolution.md` | `.asya/` directory, config schema (three files), walk-up merge, OmegaConf resolvers, stages, Python resolution |
| `research-compiler-knowledge-base.md` | Compiler rules engine, `treat-as` values, pattern matching, config extraction, tenacity/stamina signatures |
| `research-no-dockerfile.md` | Build strategies (apko, buildpacks, Cog, Wolfi/distroless), comparison matrix, golden paths |
| `research-seamless-build.md` | Build execution (local, Shipwright, CI), promotion strategies, `actor-image.lock`, two user flows |
| `artem-research-compiler-resolution.md` | Stages overview, compile-time resolution chain, `asya.yaml` role |
| `adr.no-cog.md` | Cog as supported GPU build path (revised) |
| `adr.compiler-template-not-helm.md` | Output template uses OmegaConf resolvers, not Helm |
| `xrd-v2/rfc.md` | Flat AsyncActor XRD v1alpha2 spec, two-tier convention, flavor overlap rules |

---

## 21. Open Questions

1. **Click vs argparse**: Current CLI uses argparse. Should the new CLI use
   Click?

2. **Jupyter widget framework**: ipywidgets vs JupyterLab extensions vs static
   SVG.

3. ~~**Docker Compose generation**~~: **Resolved**. `asya flow compose`
   explicitly generates `docker-compose.yaml` from effective K8s manifests
   (kustomize build output). No sidecar — lightweight Python orchestrator
   calls runtimes via Unix socket. The compose file is saved to disk and
   committed to git. See section 6.2 (Docker Compose architecture).

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

See also open questions in `research-compiler-resolution.md` (section 8) and
`research-seamless-build.md` (section 8).
