---
title: "Phase 2.3: Add AsyncActor XR querying for configuration"
status: open
priority: 1 # high
type: task
---

Enhance the webhook to query AsyncActor XR for injection configuration.

## Tasks

1. Add Kubernetes client to webhook for querying AsyncActors
2. When pod has asya.sh/actor=X, query AsyncActor X in pod's namespace
3. Extract configuration from AsyncActor spec:
   - sidecar.image (or default)
   - sidecar.resources
   - runtime.pythonExecutable
   - runtime.handlerMode
   - transport type
4. Use extracted config for injection instead of hardcoded values
5. Handle missing AsyncActor gracefully (reject pod with clear error)
6. Cache AsyncActor lookups to reduce API load

## Acceptance Criteria

- Webhook queries AsyncActor and uses its configuration
- Custom sidecar image in AsyncActor spec is used
- Custom resources in AsyncActor spec are applied
- Missing AsyncActor results in pod rejection with error message

## Technical Notes

- Use informer/cache for AsyncActor lookups (reduce API server load)
- Webhook needs RBAC to read AsyncActor resources
- Consider timeout for API calls

## Reference

See docs/rfc/rfc-crossplane.md Section 6 (Injection Flow steps 3-5)


---
**Close reason**: Closed


---
_Migrated from beads `asya-9jk`_
