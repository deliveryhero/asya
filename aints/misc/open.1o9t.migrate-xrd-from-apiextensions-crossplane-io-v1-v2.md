---
title: Migrate XRD from apiextensions.crossplane.io/v1 to v2
priority: 2 # medium
---

## Context

Crossplane v2.x (now the latest stable release) deprecates `apiextensions.crossplane.io/v1` for CompositeResourceDefinitions with the warning:

> CompositeResourceDefinition v1 is deprecated and will be removed in a future release; consider migrating to v2

Our E2E deploy script (`testing/e2e/scripts/deploy.sh`) installs Crossplane unpinned from `crossplane-stable/crossplane`, so it picks up the latest v2.x release where v1 XRDs emit this deprecation warning.

## Affected file

`deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml` — currently uses `apiextensions.crossplane.io/v1` with `claimNames`.

## Key v2 changes

1. **Claims removed** — `claimNames` field is not supported in v2. Our XRD uses claims (`AsyncActor` claim → `XAsyncActor` XR).
2. **Namespaced scope default** — v2 XRs are namespaced by default, eliminating the need for claim indirection.
3. **Connection secrets removed** — not used by us, no impact.
4. **LegacyCluster scope** — `scope: LegacyCluster` provides v1 compatibility (keeps claims), but is not the target state.

## Migration plan

### Option A: Quick bridge (LegacyCluster)
- Change apiVersion to `apiextensions.crossplane.io/v2`
- Add `scope: LegacyCluster`
- Keep `claimNames` — claims continue to work
- Silences the deprecation warning immediately

### Option B: Full migration (Namespaced)
- Change apiVersion to `apiextensions.crossplane.io/v2`
- Set `scope: Namespaced`
- Remove `claimNames` section entirely
- Rename `names.kind` from `XAsyncActor` → `AsyncActor` (users keep creating `AsyncActor` resources, just as direct XRs instead of claims)
- Update `names.plural` from `xasyncactors` → `asyncactors`
- Update Compositions (`compositeTypeRef`) to reference the new names
- Update all examples, E2E tests, and docs

### Also consider
- Pin Crossplane version in `deploy.sh` to avoid surprise breakage
- Test with Crossplane v2.2.x to verify compositions still work
- Check if `provider-aws-sqs` and `provider-kubernetes` versions are compatible with Crossplane v2.x
