---
title: "Phase 1.5: Remove injector, render full Deployment in compositions"
status: merged
priority: 2
assignee: Artem Yushkovskiy
parent: ip3ls
dependencies:
  - 8gc6
tags:
  - worktree:.worktrees/xrd-v2/af25.phase-1-5-remove-injector-render-full-deployment
  - branch:xrd-v2/af25.phase-1-5-remove-injector-render-full-deployment
  - pr:293
---

## Summary

Remove the asya-injector mutating webhook entirely. Move all sidecar injection logic into Crossplane compositions, which already control the full Deployment spec.

Without workloadRef, the composition creates the Deployment from scratch — there is nothing to mutate. The injector is a historical artifact of the pattern where users provided a raw PodSpec that needed sidecar injection.

## What the injector currently does

1. Injects asya-sidecar container with transport env vars (ASYA_TRANSPORT, ASYA_AWS_REGION, queue URL, etc.)
2. Mounts socket-dir volume (runtime <-> sidecar communication)
3. Mounts tmp volume
4. Mounts asya_runtime.py ConfigMap into runtime container
5. Overrides runtime container command to run asya_runtime.py
6. Renders state proxy sidecar containers from `spec.stateProxy[]`
7. Renders secret volume mounts from `spec.secretRefs[]`

All of this information is available to the composition at render time.

## Scope

### Compositions (all 3: SQS, RabbitMQ, PubSub)
- Render complete Deployment spec including:
  - Runtime container (image, command, env, resources, volumeMounts)
  - Sidecar container (asya-sidecar image, transport env vars, queue URL)
  - State proxy sidecar containers (from `spec.stateProxy[]`)
  - All volumes (socket-dir, tmp, runtime ConfigMap, secret volumes)
  - Secret mounts (from `spec.secretRefs[]`)
- Region/gcpProject come from Helm values (after Phase 1)
- Queue URL comes from composed queue resource status

### Remove entirely
- `src/asya-injector/` — Go component (~2k LOC)
- `deploy/helm-charts/asya-injector/` — Helm chart
- MutatingWebhookConfiguration
- cert-manager dependency for webhook TLS
- E2E test phases that deploy/wait for injector

### Update
- E2E test infrastructure (no injector deployment step)
- AGENTS.md and architecture docs (remove injector references)
- asya-crew chart (crew actors also went through injector — compositions must render their full Deployments too)

## Benefits
- One less component to deploy and maintain
- No webhook latency on pod creation
- No cert-manager dependency
- No timing bugs (webhook must be ready before pods are created)
- Composition is the single source of truth for Deployment spec
- Easier to debug — rendered Deployment is exactly what the composition produces

## Future: workloadRef
When workloadRef arrives, injection will return in a different form — likely a Crossplane composition function that patches an existing Deployment, not a webhook. This is a future concern and will be designed separately.

## Test strategy
- Unit tests: remove injector tests, add composition rendering tests
- E2E tests: actors must still deploy and process messages correctly
- `make test-unit` and `make test-e2e` must pass
