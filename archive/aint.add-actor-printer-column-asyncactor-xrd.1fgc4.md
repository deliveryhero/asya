---
title: Add ACTOR printer column to AsyncActor XRD
status: merged
priority: 2
tags:
  - type:feature
---

Add an ACTOR additionalPrinterColumn to the XRD that shows spec.actor value in default kubectl get output (priority: 0). Columns should be: NAME ACTOR STATUS READY REPLICAS TRANSPORT AGE.


---
**Close reason**: Added ACTOR printer column to XRD with priority 0, using .metadata.labels['asya.sh/actor'] jsonPath


---
_Migrated from beads `asya-537y`_
