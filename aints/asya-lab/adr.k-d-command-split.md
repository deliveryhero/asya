# ADR: Split CLI into `asya k` (K8s) and `asya d` (Docker) with top-level compile

**Status**: Accepted
**Date**: 2026-03-09
**Context**: asya-lab CLI command surface design (rfc.md §5-6, open question #18)
**Supersedes**: RFC §5 (flow/actor/msg command groups), RFC §6.2 (Docker Compose
orchestrator architecture)

## Decision

Split the CLI into three tiers based on what the command interacts with:

- **Top-level** (`asya compile`, `asya init`, `asya serve`) — purely local, no
  cluster or Docker daemon needed
- **`asya k`** (alias for `asya kube` or `asya kubernetes`) — commands that interact with Kubernetes (deploy, status, logs,
  gateway, secrets, contexts)
- **`asya d`** (alias for `asya docker` or `asya docker-compose`) — commands that interact with Docker (compose up/down, send to
  socket, logs)

Remove the `type: docker` context type. Contexts are K8s-only. Docker Compose is
a local testing tool, not a deployment target.

## Command Surface

```
asya compile <target>               # Python -> manifests + routers (local only)
asya init [--template <name>]       # scaffold .asya/
asya serve                          # local UI server

asya k edit <actor-name>            # open kustomize patch
asya k show <target>                # kustomize build -> effective manifests
asya k build <target>               # build + push images
asya k deploy <target>              # auto-compile if .py, kubectl apply
asya k undeploy <target>
asya k status <target>
asya k logs <target>
asya k call <target> '{}'           # gateway call
asya k stream <id>                  # gateway stream SSE
asya k expose <target>              # register flow with gateway
asya k send <target> '{}'           # send envelope to queue
asya k trace <id>                   # distributed trace
asya k secret create|remove|list|show
asya k context list|use

asya d up <target>                  # auto-compile + generate compose + up
asya d down <target>
asya d send <target> '{}'           # send envelope to socket
asya d logs <target>
asya d trace <id>
```

Aliases: `asya k` = `asya kube` = `asya kubernetes`, `asya d` = `asya docker`.

### Target Resolution

| Input | Detection | Behavior |
|-------|-----------|----------|
| `myflow.py` | File exists, `.py` extension | Compile from source first |
| `e_commerce.validate.process` | Dotted path, no file | Single handler (actor) |
| `order-processing` | Kebab-case name | Look up in `.asya/manifests/` |

`asya k deploy` and `asya d up` auto-compile when given a `.py` file.

## Key Design Changes

### 1. No actor/flow distinction in commands

The RFC had separate `asya flow *` and `asya actor *` command groups. These are
merged — the CLI detects whether the target is a flow (has routing) or a single
actor (one handler). From the user's perspective, they compile/deploy "a thing."

### 2. `compile` is top-level

`compile` produces manifests and router code. It does not interact with K8s or
Docker. Both `asya k deploy` and `asya d up` reuse compilation output. Putting
it under `k` would be misleading — it is a local-only operation.

### 3. Docker Compose uses sidecar + socket transport (no orchestrator)

The RFC proposed a Python orchestrator container that replaces sidecars in Docker
Compose. This is rejected. Instead, Docker Compose runs the same architecture as
K8s: real sidecars with a new **socket transport** (`ASYA_TRANSPORT=socket`).

**Socket transport**: Real Go implementation in `src/asya-sidecar/internal/transport/socket/`.
Implements the existing `Consumer`/`Producer` interface. Each actor's sidecar
listens on `/var/run/asya/mesh/<actor-name>.sock`. A shared Docker volume makes
all sockets visible to all sidecars.

Benefits:
- No lossy translation (same sidecar, same runtime, same envelope protocol)
- No new component to build and maintain (orchestrator)
- Integration tests can use socket transport to decouple from RabbitMQ/SQS
- State proxy is a shared volume with optional seed data

Constraints (acceptable for local testing):
- Single replica per actor (one consumer per socket)
- No queue-level DLQ
- No KEDA autoscaling
- Sequential FIFO delivery

### 4. Contexts are K8s-only

```yaml
# .asya/config.yaml
contexts:
  stg:
    type: kubernetes
    kubecontext: my-stg-cluster
    namespace: team-one
    gateway: https://gw.stg.internal
  prod:
    type: kubernetes
    kubecontext: my-prod-cluster
    namespace: prod
    readonly: true

default_context: stg
```

No `type: docker`. No `compose_output`. Docker is not a deployment context — it
is a local testing tool with its own command surface (`asya d`).

### 5. Docker secrets via .env.secret

When `asya d up` detects env vars mapped to K8s secrets (via `asya k secret`),
it checks `.env.secret`. If missing or incomplete, it fails with a hint:

```
Error: 2 secrets not in .env.secret (OPENAI_API_KEY, DB_PASSWORD)
  hint: asya k secret show -o env >> .env.secret && chmod 600 .env.secret
  hint: ensure .env.secret is in .gitignore (asya init adds it automatically)
```

`asya init` adds `.env.secret` to `.gitignore`. No dedicated `asya d secret`
commands — users manage the file manually with shell commands and hints from
error messages.

### 6. Three testing tiers

| Tier | What runs | Transport | Command |
|------|-----------|-----------|---------|
| pytest | Pure Python function | None (direct call) | `pytest` |
| Single actor | Runtime as HTTP server | None (HTTP) | `asya d up <actor.py>` (`@actor` handler) |
| Full flow | Sidecar + runtime per actor | Socket | `asya d up <flow.py>` |

### 7. Compiler rules out of scope

`asya k rule add/remove/list/explain` is deferred. Users edit
`.asya/compiler/rules.yaml` directly for now.

## Consequences

- RFC §5 (CLI Commands) is rewritten around `k`/`d`/top-level tiers
- RFC §6 (Context System) drops `type: docker` and all Docker dispatch logic
- RFC §6.2 (Docker Compose architecture) drops the orchestrator, replaced by
  sidecar + socket transport
- A socket transport implementation is needed in the sidecar (Go)
- `asya msg send` splits into `asya k send` (queue) and `asya d send` (socket)
- `asya flow compose` becomes `asya d up` (auto-compile + compose + start)
- Integration tests benefit from socket transport (lighter, no external infra)
