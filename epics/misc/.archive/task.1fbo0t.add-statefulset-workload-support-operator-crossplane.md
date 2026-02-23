---
title: Add StatefulSet workload support (operator + Crossplane)
status: wont_do
priority: 3 # low
type: task
tags:
  - type:feature
reason: virtual actors only
---





Implement StatefulSet support for AsyncActor workloads. Currently: operator had reconcileStatefulSet() but it returned fmt.Errorf("StatefulSet support not yet implemented"), and the Crossplane XRD accepts workload.kind: StatefulSet but the composition only renders Deployments. Neither path ever worked.

Deliverables:
1. Operator: Implement reconcileStatefulSet() to create/manage StatefulSets with stable pod identities and persistent volume claims
2. Crossplane: Add StatefulSet rendering in composition (alongside existing Deployment rendering)
3. Support PVC templates for actor-local state (e.g., model caches, aggregation buffers)
4. Unit + integration tests for StatefulSet lifecycle

This is a likely prerequisite for fan-in (asya-7qh) where aggregator actors need stable identity and persistent state (e.g., Postgres-backed merge buffers).


---
_Migrated from beads `asya-altb`_
