# ADR: Kustomize is not an extra dependency

**Status**: Accepted
**Date**: 2026-03-09
**Context**: RFC section 8.1 (kustomize-native compilation), open question 16

## Decision

Keep kustomize as the default output model. Use `kubectl apply -k` instead of
shelling out to a standalone `kustomize` binary. Do not add a `compile.mode: raw`
fallback.

## Rationale

Kustomize is bundled with kubectl since v1.14 (March 2019). `kubectl apply -k`
runs `kustomize build` + `apply` in one shot. If a user has kubectl, they have
kustomize. No extra binary to install.

The base/patches separation — compiler owns `base/`, user owns `patches/`,
recompile never destroys user edits — requires merge logic. Kustomize provides
that merge logic for free, battle-tested, with strategic merge patch semantics
that correctly handle `env[]` merge-by-name and deep map merging.

## Alternatives Considered

### `compile.mode: raw` — plain YAML without kustomization.yaml

Rejected. Removing `kustomization.yaml` saves nothing (it's auto-generated)
and breaks the base/patches separation. Users who never create patches can
already `kubectl apply -f base/` — the base directory contains valid standalone
YAML. Adding a mode flag for this adds complexity without adding capability.

### Implement merge in Python

Rejected. Reimplementing kustomize's strategic merge patch semantics in Python
is non-trivial and creates a maintenance burden. The kubectl-bundled version is
the standard.

### Helm output backend

Deferred. Helm-only shops want a different deployment model (Chart + values.yaml),
not "kustomize minus kustomization.yaml." This is a future output backend if
real user demand materializes, not a raw mode toggle.

## Consequences

- `asya flow deploy` uses `kubectl apply -k` — no standalone `kustomize` binary
  needed
- `asya flow show` shells out to `kubectl kustomize` (or `kustomize build` if
  available) to print effective manifests
- `base/*.yaml` remains valid standalone YAML — users CAN bypass kustomize with
  `kubectl apply -f base/` if they have no patches
- Minimum kubectl version: 1.14+ (released March 2019, universally available)
