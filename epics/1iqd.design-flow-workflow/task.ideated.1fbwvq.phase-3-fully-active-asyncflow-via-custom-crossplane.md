---
title: "Phase 3: Fully active AsyncFlow via custom Crossplane composition function"
priority: 3 # low
type: task
tags:
  - type:feature
---







Write a custom Crossplane composition function (Go, ~200 lines) that resolves actors by name from spec.processors, handles M:N flow membership, and manages lifecycle. Runs within Crossplane reconciliation loop — no standalone controller.

This replaces the function-extra-resources approach (Phase 2) which is limited to 1:1 flow membership via asya.sh/flow label.

Implementation:
1. Write Go composition function implementing the Crossplane function SDK (fn.crossplane.io/v1beta1)
2. Function reads spec.processors[] and spec.routers[] from the XR
3. For each actor name, queries K8s API for AsyncActor claims with asya.sh/actor=<name> label
4. Resolves actor names to resource names (populates status.actors[].resource)
5. Checks status.phase of each actor, aggregates flow readiness
6. Handles M:N relationships — no reliance on asya.sh/flow label for discovery
7. Lifecycle management:
   - Finalizer on AsyncFlow XR
   - On deletion: reads ALL other AsyncFlow XRs
   - Builds shared-actor set across flows
   - Deletes only actors exclusive to this flow (routers are always exclusive)
   - Keeps shared processor actors
8. Package as container image, deploy as Crossplane Function resource

Status fields (extending Phase 2):
  status:
    actors:
      - actor: validate-order
        resource: validate-order-eu    # Resolved resource name
        namespace: prod
        ready: true
        phase: Ready
      - actor: process-payment
        resource: payment-proc-eu
        ready: false
        phase: Creating
        sharedWith:                    # M:N visibility
          - payment-retry-flow

Depends on Phase 2 completion to validate status schema and composition pipeline patterns.


---
_Migrated from beads `asya-dbfm`_
