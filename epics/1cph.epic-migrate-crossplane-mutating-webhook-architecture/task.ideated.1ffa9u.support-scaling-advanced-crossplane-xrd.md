---
title: Support scaling.advanced in Crossplane XRD
priority: 2 # medium
type: task
tags:
  - type:feature
---




Port the scaling.advanced sub-object from asya-operator CRD to the Crossplane XRD. Fields: formula, target, activationTarget, metricType, restoreToOriginalReplicaCount. These allow users to customize KEDA scaling behavior beyond simple queue-length triggers.


---
_Migrated from beads `asya-tme`_
