---
title: Implement derived phase calculation from infrastructure statuses
status: open
priority: 2 # medium
type: task
dependencies:
  - 1cph/1cfr
  - 1cph/1ca8
  - 1cph/1crt
---

Implement complex phase derivation logic that computes AsyncActor phase from multiple infrastructure component statuses.

## Background

AsyncActor's final phase should be computed based on:
- SQS Queue status (ready/synced)
- KEDA ScaledObject status (ready, active)
- Deployment status (available, progressing)
- Replica counts (for Running vs Napping distinction)

## Target Phase Values

**Operational:**
- Running: All infrastructure ready, replicas > 0
- Napping: All infrastructure ready, replicas = 0 (scale-to-zero)
- Ready: All infrastructure ready (generic ready state)

**Transitional:**
- Creating: Resources being provisioned
- Updating: Resources being modified

**Error:**
- Degraded: Some components not ready
- Failed: Critical component failure

## Implementation Options

1. **Composition Function (Go/Python)**: Custom function for complex logic
2. **function-cel**: CEL expressions for conditional logic
3. **function-go-templating**: Complex Go templates with conditionals

## Acceptance Criteria

- Phase accurately reflects overall infrastructure health
- Phase transitions are logical and predictable
- kubectl get asyncactors shows meaningful phase

## Dependencies

Requires all infrastructure components to be added to Composition:
- asya-hm3: Deployment
- asya-pvh: ScaledObject
- asya-74f: Basic status patching


---
**Close reason**: Fixed in commit d2198ae: watch:true on Objects, DeploymentRuntimeConfig, Ready/Napping phases, label propagation, scale-to-N and resilience test sections in quickstart


---
_Migrated from beads `asya-kdu`_
