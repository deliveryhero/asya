# Plan: Init Container Code Delivery for Training Actors

## Problem Restatement

Training actors need code from a git repo for real ML experiments.
Building Docker images is too slow for fast iteration on EKS.
`cynl0` (merged) added `initContainers`/`sidecars`/`volumes` to the
AsyncActor XRD and composition. This aint delivers the example manifests
and workbench documentation to make those fields usable.

## No Code Changes

The XRD already accepts `spec.initContainers`, `spec.volumes`, and
`spec.volumeMounts`. The composition renders them correctly via `toYaml`.
This task is configuration examples and documentation only.

## Key Design Decisions

### Secret access in init containers
`spec.secretRefs` injects secrets into `asya-runtime` only (runtime-only
field). Init containers must reference secrets inline via
`env[].valueFrom.secretKeyRef` inside the init container spec. This passes
through the composition's `toYaml` rendering correctly.

### emptyDir lifetime
`emptyDir` is pod-scoped — cleared on pod restart. This is correct: fresh
clone on each pod start. If clone frequency becomes expensive, switch to git
state proxy (cy0p1) which caches the local clone.

### PYTHONPATH
Set via `spec.env` (injects into `asya-runtime`). No handler code changes
needed. Handler can `import mypackage` directly after PYTHONPATH is set.

### git-sync --one-time flag
Required for init container semantics: runs once, clones, exits. Without it,
git-sync stays alive as a continuous sync sidecar (wrong — that's `spec.sidecars`
territory).

### pip --target vs virtual env
`pip install --target=/code` installs wheels into the emptyDir directly.
Simpler than creating a venv in the init container. PYTHONPATH picks it up.

### git-sync clone layout
`git-sync:v4` creates a symlink layout: `/code/<repo>` → `/code/.git-sync/<hash>`.
Handler code must import from inside the repo subdirectory, or use
`--link` to set a stable symlink name. Examples use `--link=repo` for
a stable mount point at `/code/repo`.

## Files to Create

### 1. `examples/asyas/training-actor-git-creds-secret.yaml`
K8s Secret template (placeholder values). Operator applies once per namespace:
```bash
kubectl create secret generic git-creds -n <namespace> --from-literal=token=<pat>
```

### 2. `examples/asyas/training-actor-git-sync.yaml`
AsyncActor with `registry.k8s.io/git-sync/git-sync:v4` init container:
- `spec.volumes`: `[{name: code, emptyDir: {}}]`
- `spec.initContainers`: git-sync with `--one-time --link=repo`, GITSYNC_PASSWORD from git-creds secret
- `spec.volumeMounts`: `[{name: code, mountPath: /code}]` (adds `/code` to runtime container)
- `spec.env`: `[{name: PYTHONPATH, value: /code/repo}]`

### 3. `examples/asyas/training-actor-pip-install.yaml`
AsyncActor with `python:3.13-slim` init container:
- `spec.volumes`: `[{name: code, emptyDir: {}}]`
- `spec.initContainers`: `pip install --target=/code git+https://${GIT_TOKEN}@...@${GIT_BRANCH}`
- `spec.volumeMounts`: `[{name: code, mountPath: /code}]`
- `spec.env`: `[{name: PYTHONPATH, value: /code}]`

### 4. ONBOARDING.md update
Add "Code Delivery Options" section between "Step-by-Step" and "Data Locations".
Three tiers with concrete kubectl commands:
1. ConfigMap — small handlers (existing, ≤1MB)
2. git-sync — full repo clone at startup
3. pip-install — single pip-installable package

## Steps

- [x] Convert aint to dir with aint.md + plan.md
- [x] Create worktree `autoresearch/jf7uo.init-container-code-delivery`
- [x] Create `examples/asyas/training-actor-git-creds-secret.yaml`
- [x] Create `examples/asyas/training-actor-git-sync.yaml`
- [x] Create `examples/asyas/training-actor-pip-install.yaml`
- [x] Update ONBOARDING.md with "Code Delivery Options" section
- [x] Commit, push, PR (#460)
- [x] Set aint status to pushed
