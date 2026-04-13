---
title: Add Deployment-level field pass-through in XRD workload section
status: merged
priority: 2
parent: 00000
---

Implement hybrid approach for spec.workload in the Crossplane XRD: add x-kubernetes-preserve-unknown-fields on the workload object itself (already exists on template), then update the composition to pass through unknown Deployment-level fields (strategy, minReadySeconds, progressDeadlineSeconds, etc.) to the generated manifest. Explicitly define the most common fields (strategy with enum validation, minReadySeconds, progressDeadlineSeconds) for discoverability via kubectl explain, while the preserve-unknown-fields escape hatch lets users set any other Deployment/StatefulSet field without waiting for XRD updates. Composition changes: iterate over workload keys, skip managed keys (kind, replicas, template), and dump the rest into the Deployment manifest. Also consider StatefulSet-specific fields like volumeClaimTemplates and podManagementPolicy.


---
_Migrated from beads `asya-jur`_
