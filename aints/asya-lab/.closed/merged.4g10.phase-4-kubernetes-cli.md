---
title: "Phase 4: Kubernetes CLI (apply, delete, status, logs) + asya build"
priority: 2 # medium
assignee: Artem Yushkovskiy
tags:
  - worktree:.worktrees/.worktrees/asya-lab/4g10.phase-4-kubernetes-cli
  - branch:asya-lab/4g10.phase-4-kubernetes-cli
  - pr:298
dependencies:
  - 5ifn
reason: "PR #298 merged"
---





## Scope

Kubernetes commands (`asya k`) that interact with a cluster, plus `asya build`
(top-level, local-only image building).

`build` is top-level because it runs locally (Docker/Podman on developer machine),
not on a K8s cluster. Same rationale as `compile` — see `adr.k-d-command-split.md`.

### 4a. asya k apply <target> [--context ctx]

1. Auto-compile if given `.py` file
2. Select overlay for active context
3. `kustomize build | kubectl apply --server-side --field-manager=asya-flow-<name>`
4. Print each command before execution (`+` prefix)
5. Idempotent (SSA merges, re-running is safe)
6. Readonly contexts: error with hint to use GitOps

### 4b. asya k delete <target> [--context ctx]

- `kubectl delete` by flow labels (`asya.sh/flow=<name>`)
- Deletes all actors in the flow (routers + processors)
- Readonly contexts: error

### 4c. asya build <target>

Thin command runner for image building (top-level, no cluster needed):

1. Resolve target to build entries in config (module → image + command)
2. Run opaque shell `command` with variable substitution (`${.image}`, `${arg:tag}`)
3. `--push` flag appends registry push after build
4. Multi-image builds: sequential, fail-fast, `[build 1/N]` progress prefixes

```bash
asya build order-processing --arg tag=v1.2
# [build 1/2] docker build -t ghcr.io/org/ecom:v1.2 .
# [build 2/2] docker build -t ghcr.io/org/shared:v1.2 .

asya build order-processing --arg tag=v1.2 --push
# [build 1/2] docker build -t ghcr.io/org/ecom:v1.2 .
# [push  1/2] docker push ghcr.io/org/ecom:v1.2
```

- Asya is a thin command runner, not a build system
- `command` is a single shell string
- Unresolved `${arg:*}` at build time = hard error
- No Asya-imposed image tag convention (CD concern)

### 4d. asya k status <target> [--context ctx]

- Live cluster state: `kubectl get asyncactor -l asya.sh/flow=<name>`
- Shows replicas, queue depth, pod status
- Adds DEPLOYED column to the status table (extends `asya status`)

### 4e. asya k logs <target> [--context ctx]

- `kubectl logs -l asya.sh/flow=<name>` with colored per-actor output
- Follow mode with `--follow`

### 4f. Supporting commands

- `asya k context list|use` — switch K8s context
- `asya k secret create|remove|list|show` — K8s secretKeyRef mappings
- `asya k edit <actor>` — open kustomize patch in `common/` with pre-populated
  commented template

## Dependencies

- [5ifn] Phase 3: Local CLI

## References

- `.aint/aints/asya-lab/rfc.md` §5.1 — top-level commands (asya build)
- `.aint/aints/asya-lab/rfc.md` §5.2 — Kubernetes commands
- `.aint/aints/asya-lab/rfc.md` §5.9 — apply semantics, SSA, idempotency
- `.aint/aints/asya-lab/rfc.md` §5.10 — readonly enforcement
- `.aint/aints/asya-lab/rfc.md` §10.2 — what asya k apply does
- `.aint/aints/asya-lab/rfc.md` §10.3 — rollback (deferred)
- `.aint/aints/asya-lab/rfc.md` §11 — image building, three build paths
- `.aint/aints/asya-lab/research-seamless-build.md` §7 — build command design
- `.aint/aints/asya-lab/research-compiler-resolution.md` §2 — build entry schema
