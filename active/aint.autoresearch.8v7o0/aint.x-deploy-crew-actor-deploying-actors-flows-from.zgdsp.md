---
title: x-deploy crew actor for deploying actors/flows from git
status: open
priority: 1 # high
tags: [autoresearch, crew, deployment]
dependencies: [8v7o0/cy0p1]
---

## Context

The autoresearch orchestrator needs to deploy/redeploy training and evaluation
actors during the experiment loop (e.g., new architecture, updated handler).
Today, only users with kubectl access can deploy. x-deploy brings deployment
into the mesh as a routable crew actor.

## Design

x-deploy is a **crew actor** (like x-sink, x-sump, x-pause), deployed once per
namespace by the cluster admin.

### Envelope Interface

```json
{
  "payload": {
    "branch": "experiment/resnet-v3",
    "manifest_path": "manifests/train-actor.yaml",
    "mode": "apply-and-wait"
  }
}
```

### Modes

- **apply-and-wait** (default): `asya compile` + `kubectl apply`, poll until
  Deployment/AsyncActor is Ready, return status in envelope. Timeout: 5min.
- **fire-and-forget**: `asya compile` + `kubectl apply`, return immediately.
  Set via `payload.mode` or header `x-asya-deploy-mode`.

### Mounts

- Git state proxy (read-only): mounts the specified branch at `/code/`
- Reads manifest from `/code/{manifest_path}`
- Runs `asya compile` if manifest is a flow DSL file (`.py`)
- Runs `kubectl apply -f` on the compiled/raw manifest

### Security (v0, Single-Tenant)

- ServiceAccount with namespace-scoped Role:
  - create/update/delete AsyncActor in own namespace
  - create/update/delete ConfigMap in own namespace
  - get/list Deployments, Pods (for readiness polling)
- Image allowlist: env var `ALLOWED_IMAGE_PREFIXES` (e.g., `asya/,ghcr.io/org/`)
- Resource limit enforcement: reject manifests requesting more than configured
  max CPU/memory per actor

### Failure Handling

Standard Asya retry policy. If deployment fails after retries (e.g., image pull
error, invalid manifest), envelope routes to x-sump (DLQ). The orchestrator
sees a failed result and can adjust.

### What x-deploy Does NOT Do

- Build Docker images (separate concern, deferred)
- Deploy to other namespaces (namespace-scoped only)
- Manage secrets (reads existing secrets, doesn't create them)

## Testing

- Unit: manifest validation (allowlist, resource limits)
- Component: deploy an AsyncActor from git branch, verify it starts
- Component: apply-and-wait returns success after pod is Ready
- Component: invalid manifest → DLQ routing
