---
title: Support scaling.advanced in Crossplane XRD
status: merged
priority: 3 # low
assignee: Artem Yushkovskiy
tags:
  - type:feature
  - pr:276
---


Port the scaling.advanced sub-object from asya-operator CRD to the Crossplane XRD. Fields: formula, target, activationTarget, metricType, restoreToOriginalReplicaCount. These allow users to customize KEDA scaling behavior beyond simple queue-length triggers.


_Migrated from beads `asya-tme`_
