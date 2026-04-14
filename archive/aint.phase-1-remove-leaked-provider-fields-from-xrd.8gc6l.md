---
title: "Phase 1: Remove leaked provider fields from XRD"
status: merged
priority: 2
assignee: Artem Yushkovskiy
dependencies:
  - u5pdc
tags:
  - worktree:.worktrees/xrd-v2/8gc6.phase-1-remove-leaked-provider-fields-from-xrd
  - branch:xrd-v2/8gc6.phase-1-remove-leaked-provider-fields-from-xrd
  - pr:292
---

## Summary

Remove `region`, `gcpProject`, `providerConfigRef`, and `irsa` from the AsyncActor XRD spec. These are provider-specific concerns that leaked into the user-facing API.

## Scope

### XRD
- Remove 4 fields from `xrd-asyncactor.yaml`: `region`, `gcpProject`, `providerConfigRef`, `irsa`

### Compositions (all 3: SQS, RabbitMQ, PubSub)
- Remove reads of `$xr.spec.region`, `$xr.spec.gcpProject`, `$xr.spec.providerConfigRef`, `$xr.spec.irsa`
- These already have Helm values defaults — compositions just stop reading per-actor overrides

### Injector
- Stop reading `spec.region` and `spec.gcpProject` from the XR
- The injector still needs these values to set `ASYA_AWS_REGION` / `ASYA_PUBSUB_PROJECT_ID`
  on the sidecar container — but it should read them from its **own Helm config**
  (e.g., `--set awsRegion=eu-west-1`) instead of from each XR
- Update `src/asya-injector/internal/webhook/asyncactor.go` and `injection/config.go`
- Update injector Helm chart values to accept `awsRegion` and `gcpProjectId`

### Consumers (update all that set these fields)
- Examples in `examples/asyas/` (e.g., `fully-configured-actor.yaml`)
- Helm chart values (`asya-actor/values.yaml`, `asya-crew/templates/`)
- Test manifests in `testing/e2e/`
- Any docs referencing these fields

### function-asya-flavors
- Remove these fields from the workloadFields whitelist (they were in the old infrastructureFields blacklist)

## Test strategy
- Unit tests: update function-asya-flavors tests, injector tests
- E2E tests: should pass since nothing depends on per-actor provider overrides
- All fields already have defaults from Helm values

## Why separate PR
This is independent of the workload flattening. Smaller, safer change that reduces noise before the big structural refactor.
