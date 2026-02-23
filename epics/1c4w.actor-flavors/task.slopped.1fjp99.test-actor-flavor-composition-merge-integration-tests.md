---
title: "Test: Actor flavor composition and merge in integration tests"
priority: 2 # medium
type: task
---




Add integration tests for actor flavor composition.

RFC: docs/rfc/actor-flavors/rfc-actor-flavors.md

Test scenarios:
1. Single flavor: Actor with one flavor gets correct config from EnvironmentConfig
2. Multiple flavors: Actor with [flavor-a, flavor-b] gets merged config, later wins on conflicts
3. Env var merge: Env vars from multiple flavors are merged by name (not replaced)
4. Actor override: Actor inline env var overrides same-name flavor env var
5. Secret reference: Flavor with valueFrom/secretKeyRef works correctly
6. No flavors: Actor without flavors field works exactly as before (backward compatibility)
7. Missing flavor: Actor references a flavor that doesn't exist (expected behavior: error or skip, TBD)
8. Flavor update: Changing a flavor EnvironmentConfig causes actors to reconcile with new values

Test location: testing/integration/ or testing/component/ (depending on scope)
Consider whether this needs a Kind cluster (Crossplane) or can run in Docker Compose with mock Crossplane.


---
_Migrated from beads `asya-voc4`_
