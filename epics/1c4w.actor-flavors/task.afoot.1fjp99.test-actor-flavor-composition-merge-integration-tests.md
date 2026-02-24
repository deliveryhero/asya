---
title: "Test: Actor flavor composition and merge in integration tests"
priority: 2 # medium
type: task
---





Test actor flavors by migrating E2E test actors to use flavors — not a dedicated isolated test suite.

## Approach

Migrate existing E2E test actor manifests to use `spec.flavors`, so the existing E2E test suite
implicitly exercises the full flavor resolution pipeline (function-asya-flavors → function-go-templating
→ Deployment + ScaledObject). This is strictly better than an isolated test because it validates
the actual Crossplane pipeline execution, EnvironmentConfig label-matching with the live CRD, and
backward compat (actors without flavors) in one pass.

## Implementation

1. Create EnvironmentConfig for a standard test actor workload (e.g. `asya-test-actor` flavor
   with typical compute + scaling settings for E2E actors)
2. Deploy the EnvironmentConfig as part of E2E setup (alongside existing test infrastructure)
3. Update E2E test actor manifests to add `spec.flavors: [asya-test-actor]`:
   - `testing/e2e/charts/asya-test-actors/` templates
   - Dynamic test manifests in `test_crossplane_e2e.py` (`_actor_manifest()` helper)
4. Leave at least one test actor without flavors to cover backward compat (scenario 6)

## Scenarios covered by E2E migration

1. Single flavor - covered by E2E migration (most test actors use one flavor)
2. Multiple flavors - add second flavor to one test actor (e.g. `asya-test-actor` + `asya-test-env-vars`)
3. Env var merge - test inline env var in actor spec overrides same-name env var from flavor
4. Actor override - covered inline
6. No flavors - keep at least one test actor unflavored

## Deferred scenarios (add EnvironmentConfigs in E2E setup)

5. Secret reference - flavor with `valueFrom/secretKeyRef`
7. Missing flavor - test that actor referencing nonexistent flavor produces a clear error
8. Flavor update - update EnvironmentConfig, verify actor reconciles with new values

## Notes

RFC: ./rfc.md


---
_Migrated from beads `asya-voc4`_
