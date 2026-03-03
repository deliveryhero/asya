---
title: Support scaling.advanced in Crossplane XRD
priority: 3 # medium
tags:
  - type:feature
---


Leftover from [[1cph]]

Port the scaling.advanced sub-object from asya-operator CRD to the Crossplane XRD. Fields: formula, target, activationTarget, metricType, restoreToOriginalReplicaCount. These allow users to customize KEDA scaling behavior beyond simple queue-length triggers.


---
_Migrated from beads `asya-tme`_
