---
title: Workbench devcontainer setup
status: open
priority: 3 # low
tags: [tier-1, autoresearch, workbench, devcontainer]
---

## Context

Minimal persistent dev environment for running Claude Code and orchestrating
Asya flows. Not Asya-specific infrastructure — just a VS Code devcontainer
with the right tools.

## Scope

Based on VS Code dev containers (https://code.visualstudio.com/docs/devcontainers/containers).

### Container Image

Base: `mcr.microsoft.com/devcontainers/base:ubuntu` (minimal VS Code image).

Post-install script installs:
- `claude` CLI (Claude Code)
- `git` + `git-aint`
- `kubectl` + `helm`
- `uv` (Python package manager)
- `asya` CLI
- `tensorboard`
- `tmux`

### Storage

- PVC (EBS gp3, 50-100GB): `/home/dev/` — git repo, worktrees, `.claude/`, `.aint/`
- S3 Mountpoint CSI (future): `/datasets/` — dataset exploration

### Access

- kubectl: ServiceAccount with workbench-role (manage AsyncActor + ConfigMap)
- git: SSH key or token in secret
- S3: IRSA or env credentials
- Gateway: in-cluster service URL

### devcontainer.json

```json
{
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
  "postCreateCommand": "bash .devcontainer/setup.sh",
  "mounts": [
    "source=workbench-pvc,target=/home/dev,type=volume"
  ],
  "remoteEnv": {
    "KUBECONFIG": "/home/dev/.kube/config"
  }
}
```

## Deliverables

1. `.devcontainer/devcontainer.json`
2. `.devcontainer/setup.sh` (post-install script)
3. K8s manifests: PVC, ServiceAccount, Role, RoleBinding
4. Documentation: how to launch workbench on EKS

## Current Status (2026-04-21)

Workbench pod is deployed and surviving restarts. Known blockers:

1. **Cannot build images for training actors** — need init container support
   (cynl0 + jf7uo) to deliver code via git-sync or pip install
2. **PVCs not shareable** — EBS RWO volumes can't be mounted to both workbench
   and training actors simultaneously. EFS CSI driver being installed separately
   (tracked in g87or)

## Not in Scope

- Coder platform integration (future)
- Multi-user workbench management
- GPU access from workbench (use flows for compute)
