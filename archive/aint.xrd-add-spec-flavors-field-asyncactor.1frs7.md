---
title: "XRD: Add spec.flavors field to AsyncActor"
status: merged
priority: 2
parent: 00000
---

Add an optional 'flavors' field to the AsyncActor XRD schema.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md

Changes:
- File: deploy/helm-charts/asya-crossplane/templates/xrd-asyncactor.yaml
- Add 'flavors' property to spec schema:
  flavors:
    type: array
    maxItems: 8
    items:
      type: string
    description: List of flavor names (EnvironmentConfigs) to compose. Applied left-to-right; later flavors override earlier ones. Actor inline spec is applied last and always wins.
- Field is optional (no default, no required)
- Backward compatible: existing actors without flavors work unchanged

Testing:
- Validate XRD applies cleanly to a Kind cluster
- Verify existing AsyncActor examples still work without flavors field
- Verify an AsyncActor with flavors: [test] is accepted by the XRD validation


---
**Close reason**: Implemented in PR #175. Added spec.flavors array field to AsyncActor XRD.


---
_Migrated from beads `asya-cewp`_
