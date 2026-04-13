---
title: Remove actorName field, use asya.sh/actor label instead
status: merged
priority: 2
tags:
  - type:bug
---

The Crossplane XRD introduced spec.actorName to override the logical actor name for queue naming. However, the asya-operator already had a well-established pattern using the asya.sh/actor label for this purpose. Using a label is more Kubernetes-native and consistent with how other systems (e.g. service mesh, KEDA) use labels for identity. Remove the actorName field from the XRD and update the Composition to read the actor name from the asya.sh/actor label on the AsyncActor Claim, falling back to metadata.name. Update the migration doc accordingly.


---
**Close reason**: Removed spec.actorName from XRD, composition now reads asya.sh/actor label from claim metadata (propagated to XR by Crossplane). Branch: asya-l4d-remove-actorname


---
_Migrated from beads `asya-l4d`_
