---
title: "CLI: asya k apply/delete/status/logs (Kubernetes interaction)"
priority: 2 # medium
---

## Scope

Implement Kubernetes-facing CLI commands under `asya k`:

### asya k apply <target> [--context ctx]

1. Auto-compile if given `.py` file
2. Select overlay for active context
3. `kustomize build | kubectl apply --server-side --field-manager=asya-flow-<name>`
4. Print each command before execution (`+` prefix)
5. Idempotent (SSA merges, re-running is safe)
6. Readonly contexts: error with hint to use GitOps

### asya k delete <target> [--context ctx]

- `kubectl delete` by flow labels (`asya.sh/flow=<name>`)
- Deletes all actors in the flow (routers + processors)
- Readonly contexts: error

### asya k status <target> [--context ctx]

- Live cluster state: `kubectl get asyncactor -l asya.sh/flow=<name>`
- Shows replicas, queue depth, pod status
- Adds DEPLOYED column to the status table (extends `asya status`)

### asya k logs <target> [--context ctx]

- `kubectl logs -l asya.sh/flow=<name>` with colored per-actor output
- Follow mode with `--follow`

### Supporting commands

- `asya k context list|use` — switch K8s context
- `asya k secret create|remove|list|show` — K8s secretKeyRef mappings
- `asya k edit <actor>` — open kustomize patch in `common/` with pre-populated
  commented template

## Dependencies

- [leuo] Show/status (for local status table)
- [hox4] Manifest stamping (for manifest directory structure)
- [pyt1] Config system (for contexts, readonly enforcement)

## References

- `.aint/aints/asya-lab/rfc.md` §5.2 — Kubernetes commands
- `.aint/aints/asya-lab/rfc.md` §5.9 — apply semantics, SSA, idempotency
- `.aint/aints/asya-lab/rfc.md` §5.10 — readonly enforcement
- `.aint/aints/asya-lab/rfc.md` §10.2 — what asya k apply does
- `.aint/aints/asya-lab/rfc.md` §10.3 — rollback (deferred)
