---
title: "Phase 2: Semi-active AsyncFlow via function-extra-resources"
status: open
priority: 3
tags:
  - type:feature
---

Outdated? see ADR.




Add function-extra-resources to AsyncFlow composition pipeline to enable automatic actor discovery and status aggregation. This is the 'semi-active' phase — no custom code, just existing Crossplane functions.

Implementation:
1. Install function-extra-resources in cluster (add to asya-crossplane Helm chart)
2. Add pipeline step to AsyncFlow composition:
   - Use FromCompositeFieldPath selector to discover AsyncActor claims by asya.sh/flow=<flow-name> label
   - matchLabels key: asya.sh/flow, type: FromCompositeFieldPath, valueFromFieldPath: metadata.name
3. Add function-go-templating step to aggregate statuses:
   - Iterate over discovered actors
   - Check each actor's status.phase
   - Compute flow readiness (readyActors / totalActors)
   - Set AsyncFlow status: phase (Ready/Degraded/Creating), conditions (FlowReady, ActorsResolved)
4. Emit XR status patch with aggregated data

Prerequisites:
- Router actors created by AsyncFlow already have asya.sh/flow label (from Phase 1)
- Processor actors need asya.sh/flow label too (set by CLI during deployment or by user)

Limitation: asya.sh/flow label is 1:1 — an actor can only belong to ONE flow.
For M:N support, Phase 3 (custom composition function) is needed.

Status fields added to AsyncFlow XRD:
  status:
    phase: Ready|Degraded|Creating
    readyActors: 3
    totalActors: 4
    conditions:
      - type: FlowReady
        status: 'True'|'False'
      - type: ActorsResolved
        status: 'True'|'False'
        message: 'Actor process-payment not found'


_Migrated from beads `asya-qdlq`_
