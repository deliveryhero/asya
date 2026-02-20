---
title: Add required spec.actor field to AsyncActor XRD
status: done
priority: 2 # medium
type: task
tags:
  - type:feature
---




Add spec.actor as a required field to the AsyncActor XRD schema. This is the logical actor identity used for queue naming and message routing, decoupled from metadata.name (resource identity). Update composition to read spec.actor instead of labels for actor name resolution.


---
**Close reason**: Added spec.actor as required field to XRD, updated composition to use spec.actor instead of labels, added tests and updated docs


---
_Migrated from beads `asya-v2hs`_
