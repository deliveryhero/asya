---
title: Extend AsyncActor XRD with initContainers and custom sidecars
status: pushed
priority: 1 # high
tags:
  - tier-2
  - autoresearch
  - crossplane
  - xrd
---


## Context

AsyncActor XRD currently supports `spec.volumes` and `spec.volumeMounts` but NOT
init containers or custom sidecar containers. Only asya-managed state proxy
containers can be added (via `spec.stateProxy[].connector`).

This blocks code delivery patterns needed for autoresearch:
- **git-sync init container**: clone repo branch at pod startup (read-only)
- **git finalizer sidecar**: commit + push on pod shutdown (for dev actors)

## Scope

Add to XRD (`xrd-asyncactor.yaml`):

```yaml
spec:
  initContainers:           # list of init container specs
    - name: git-sync
      image: registry.k8s.io/git-sync/git-sync:v4
      env: [...]
      volumeMounts: [...]

  sidecars:                 # list of additional sidecar container specs
    - name: git-finalizer
      image: asya/git-finalizer:latest
      env: [...]
```

Update composition (`composition-asyncactor.yaml`) to render these into the
Deployment pod spec alongside asya-sidecar and state proxy containers.

Both fields use `x-kubernetes-preserve-unknown-fields: true` to allow full
container spec flexibility.

## Testing

- Unit: composition renders init containers into pod spec
- Unit: composition renders custom sidecars into pod spec alongside asya-sidecar
- E2E: deploy actor with git-sync init container, verify code is available
