---
title: Decouple runtime ConfigMap provisioning from operator
status: merged
priority: 2
parent: h0mji
dependencies:
  - 1fm4
---

Move the `asya-runtime` ConfigMap creation out of the operator into a standalone mechanism.

## Context

The operator creates an `asya-runtime` ConfigMap containing `asya_runtime.py` in the actor's namespace. This ConfigMap is shared across all actors and is NOT owned by any single AsyncActor. With the operator being removed, this provisioning must happen elsewhere.

## Options

1. **Include in asya-crossplane Helm chart** (recommended) — add a ConfigMap template that ships `asya_runtime.py` content. Simple, deployed once per namespace.
2. **Separate namespace-setup chart** — if the crossplane chart shouldn't own runtime concerns
3. **Crossplane Composition** — add as a composed resource (but it's shared, not per-actor)

## Tasks

1. Choose provisioning mechanism (recommend option 1)
2. Embed `asya_runtime.py` content into the chosen mechanism
3. Ensure ConfigMap is created in actor namespaces before pods start
4. Verify injector's ConfigMap volume mount (`asya-runtime`) still resolves correctly
5. Remove the runtime ConfigMap creation code from operator (will happen in asya-pb5)

## Acceptance Criteria

- `asya-runtime` ConfigMap exists in actor namespace without operator running
- Pods with injected sidecar can mount the runtime script at `/opt/asya/asya_runtime.py`
- Runtime container starts successfully with the mounted script
- ConfigMap content matches `src/asya-runtime/asya_runtime.py`

## Technical Notes

- Operator creates ConfigMap via `reconcileRuntimeConfigMap()` at `asya_controller.go:622-671`
- Runtime loader: `src/asya-operator/internal/runtime/loader.go`
- ConfigMap name: `asya-runtime`, key: `asya_runtime.py`
- The ConfigMap is namespace-scoped and shared (not per-actor)
- Injector mounts it at `/opt/asya/asya_runtime.py` with mode 0755

## Reference

Operator source: src/asya-operator/internal/runtime/
Runtime source: src/asya-runtime/asya_runtime.py


---
**Close reason**: Resolved in PR #146 - runtime ConfigMap added to asya-crossplane Helm chart as template with symlinked asya_runtime.py


---
_Migrated from beads `asya-57z`_
